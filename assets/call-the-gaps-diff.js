/**
 * Call the Gaps — client-side text diff (paragraph Myers/LCS, token pass on
 * fuzzy paragraphs, move relabelling). Move pass thresholds (tune on desk):
 *   MOVE_MIN_TOKENS = 6 — ignore tiny spans for move pairing
 *   MOVE_MIN_SIMILARITY = 0.72 — Jaccard on normalised token bags
 *   MOVE_MAX_LEN_RATIO = 1.45 — |lenA − lenB| / max(lenA, lenB)
 */
(function (global) {
  "use strict";

  var MOVE_MIN_TOKENS = 6;
  var MOVE_MIN_SIMILARITY = 0.72;
  var MOVE_MAX_LEN_RATIO = 1.45;

  var CJK_RE = /[\u3400-\u9FFF\uF900-\uFAFF]/;
  var LATIN_WORD_RE = /[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)*/;

  function isCjk(ch) {
    return CJK_RE.test(ch);
  }

  function tokenize(text) {
    var tokens = [];
    var i = 0;
    var n = text.length;
    while (i < n) {
      var ch = text.charAt(i);
      if (/\s/.test(ch)) {
        var ws = ch;
        i++;
        while (i < n && /\s/.test(text.charAt(i))) {
          ws += text.charAt(i);
          i++;
        }
        tokens.push({ t: "ws", v: ws });
        continue;
      }
      if (isCjk(ch)) {
        tokens.push({ t: "cjk", v: ch });
        i++;
        continue;
      }
      var rest = text.slice(i);
      var m = rest.match(LATIN_WORD_RE);
      if (m) {
        tokens.push({ t: "word", v: m[0] });
        i += m[0].length;
        continue;
      }
      tokens.push({ t: "sym", v: ch });
      i++;
    }
    return tokens;
  }

  function tokenKey(tok) {
    if (tok.t === "ws") return "\0ws";
    if (tok.t === "cjk") return tok.v;
    return tok.v.toLowerCase();
  }

  function myersDiff(aKeys, bKeys) {
    var n = aKeys.length;
    var m = bKeys.length;
    var max = n + m;
    var v = {};
    v[1] = 0;
    var trace = [];

    for (var d = 0; d <= max; d++) {
      trace.push(Object.assign({}, v));
      for (var k = -d; k <= d; k += 2) {
        var x;
        if (k === -d || (k !== d && v[k - 1] < v[k + 1])) {
          x = v[k + 1];
        } else {
          x = v[k - 1] + 1;
        }
        var y = x - k;
        while (x < n && y < m && aKeys[x] === bKeys[y]) {
          x++;
          y++;
        }
        v[k] = x;
        if (x >= n && y >= m) {
          return backtrack(trace, n, m);
        }
      }
    }
    return backtrack(trace, n, m);
  }

  function backtrack(trace, n, m) {
    var x = n;
    var y = m;
    var ops = [];
    for (var d = trace.length - 1; d >= 0; d--) {
      var v = trace[d];
      var k = x - y;
      var prevK;
      if (k === -d || (k !== d && v[k - 1] < v[k + 1])) {
        prevK = k + 1;
      } else {
        prevK = k - 1;
      }
      var prevX = v[prevK];
      var prevY = prevX - prevK;
      while (x > prevX && y > prevY) {
        ops.push({ type: "equal", ai: x - 1, bi: y - 1 });
        x--;
        y--;
      }
      if (d === 0) break;
      if (x === prevX) {
        ops.push({ type: "insert", bi: y - 1 });
        y--;
      } else {
        ops.push({ type: "delete", ai: x - 1 });
        x--;
      }
    }
    ops.reverse();
    return ops;
  }

  function opsToSegments(tokensA, tokensB, ops) {
    var segments = [];
    var i = 0;
    while (i < ops.length) {
      if (ops[i].type === "equal") {
        var eqA = [];
        var eqB = [];
        while (i < ops.length && ops[i].type === "equal") {
          eqA.push(tokensA[ops[i].ai]);
          eqB.push(tokensB[ops[i].bi]);
          i++;
        }
        segments.push({ type: "equal", a: eqA, b: eqB });
        continue;
      }
      if (ops[i].type === "delete") {
        var del = [];
        while (i < ops.length && ops[i].type === "delete") {
          del.push(tokensA[ops[i].ai]);
          i++;
        }
        segments.push({ type: "delete", a: del, b: [] });
        continue;
      }
      var ins = [];
      while (i < ops.length && ops[i].type === "insert") {
        ins.push(tokensB[ops[i].bi]);
        i++;
      }
      segments.push({ type: "insert", a: [], b: ins });
    }
    return segments;
  }

  function splitParagraphs(text) {
    return text
      .replace(/\r\n/g, "\n")
      .split(/\n\s*\n/)
      .map(function (s) { return s.replace(/\s+/g, " ").trim(); })
      .filter(Boolean);
  }

  function paraKey(p) {
    return normaliseForMove(p);
  }

  function opsToParaSegments(parasA, parasB, ops) {
    var segments = [];
    var i = 0;
    while (i < ops.length) {
      if (ops[i].type === "equal") {
        var eqA = [];
        var eqB = [];
        while (i < ops.length && ops[i].type === "equal") {
          eqA.push(parasA[ops[i].ai]);
          eqB.push(parasB[ops[i].bi]);
          i++;
        }
        for (var j = 0; j < eqA.length; j++) {
          segments.push({ type: "equal", textA: eqA[j], textB: eqB[j] });
        }
        continue;
      }
      if (ops[i].type === "delete") {
        var del = [];
        while (i < ops.length && ops[i].type === "delete") {
          del.push(parasA[ops[i].ai]);
          i++;
        }
        del.forEach(function (p) {
          segments.push({ type: "delete", textA: p, textB: "" });
        });
        continue;
      }
      var ins = [];
      while (i < ops.length && ops[i].type === "insert") {
        ins.push(parasB[ops[i].bi]);
        i++;
      }
      ins.forEach(function (p) {
        segments.push({ type: "insert", textA: "", textB: p });
      });
    }
    return segments;
  }

  function wordTokenCount(text) {
    if (!text) return 0;
    return tokenize(text).filter(function (t) { return t.t !== "ws"; }).length;
  }

  function segmentPlain(side, seg) {
    return side === "a" ? seg.textA : seg.textB;
  }

  function refineSegmentWithTokenDiff(seg) {
    if (seg.type !== "equal" || !seg.textA || !seg.textB) return seg;
    if (paraKey(seg.textA) === paraKey(seg.textB)) return seg;
    var tokensA = tokenize(seg.textA);
    var tokensB = tokenize(seg.textB);
    var packA = contentMaps(tokensA);
    var packB = contentMaps(tokensB);
    var contentA = packA.map.map(function (i) { return tokensA[i]; });
    var contentB = packB.map.map(function (i) { return tokensB[i]; });
    var ops = myersDiff(packA.keys, packB.keys);
    var inner = opsToSegments(contentA, contentB, ops);
    return { type: "intra", textA: seg.textA, textB: seg.textB, inner: inner };
  }

  function normaliseForMove(s) {
    return s.toLowerCase().replace(/\s+/g, " ").trim();
  }

  function jaccardStrings(a, b) {
    if (!a && !b) return 1;
    if (!a || !b) return 0;
    var sa = normaliseForMove(a).split(/\s+/).filter(Boolean);
    var sb = normaliseForMove(b).split(/\s+/).filter(Boolean);
    if (!sa.length || !sb.length) return normaliseForMove(a) === normaliseForMove(b) ? 1 : 0;
    var setB = {};
    sb.forEach(function (w) { setB[w] = true; });
    var inter = 0;
    sa.forEach(function (w) {
      if (setB[w]) inter++;
    });
    return inter / (sa.length + sb.length - inter);
  }

  function contentTokenCount(seg) {
    if (seg.type === "intra" && seg.inner) {
      var n = 0;
      seg.inner.forEach(function (s) {
        if (s.type === "equal") n += s.a.filter(function (t) { return t.t !== "ws"; }).length;
      });
      return n;
    }
    if (seg.type === "equal") return wordTokenCount(seg.textA);
    return Math.max(wordTokenCount(seg.textA), wordTokenCount(seg.textB));
  }

  function detectMoves(segments) {
    var nextId = 1;
    var deletes = [];
    var inserts = [];
    segments.forEach(function (seg, idx) {
      if (seg.type === "delete" && wordTokenCount(seg.textA) >= MOVE_MIN_TOKENS) {
        deletes.push({ idx: idx, text: seg.textA });
      } else if (seg.type === "insert" && wordTokenCount(seg.textB) >= MOVE_MIN_TOKENS) {
        inserts.push({ idx: idx, text: seg.textB });
      }
    });

    var usedIns = {};
    deletes.forEach(function (d) {
      var best = null;
      var bestScore = MOVE_MIN_SIMILARITY;
      inserts.forEach(function (ins, ii) {
        if (usedIns[ii]) return;
        var segD = segments[d.idx];
        var segI = segments[ins.idx];
        var lenA = wordTokenCount(segD.textA);
        var lenB = wordTokenCount(segI.textB);
        var ratio = Math.abs(lenA - lenB) / Math.max(lenA, lenB, 1);
        if (ratio > MOVE_MAX_LEN_RATIO) return;
        var sim = jaccardStrings(d.text, ins.text);
        if (paraKey(d.text) === paraKey(ins.text)) sim = 1;
        if (sim >= bestScore) {
          bestScore = sim;
          best = { ins: ins, ii: ii };
        }
      });
      if (best) {
        usedIns[best.ii] = true;
        var id = "mv-" + nextId++;
        var segDel = segments[d.idx];
        var segIns = segments[best.ins.idx];
        segments[d.idx] = {
          type: "move",
          id: id,
          textA: segDel.textA,
          textB: segIns.textB
        };
        segments[best.ins.idx] = { type: "move-gap", hide: true };
      }
    });

    return segments.filter(function (s) { return !s.hide; });
  }

  function snippet(text, max) {
    max = max || 72;
    var t = text.replace(/\s+/g, " ").trim();
    if (t.length <= max) return t;
    return t.slice(0, max - 1) + "\u2026";
  }

  function contentMaps(tokens) {
    var map = [];
    var keys = [];
    for (var i = 0; i < tokens.length; i++) {
      if (tokens[i].t === "ws") continue;
      map.push(i);
      keys.push(tokenKey(tokens[i]));
    }
    return { map: map, keys: keys };
  }

  function compareTexts(srcText, tgtText) {
    var parasA = splitParagraphs(srcText);
    var parasB = splitParagraphs(tgtText);
    if (!parasA.length && srcText.trim()) parasA = [srcText.trim()];
    if (!parasB.length && tgtText.trim()) parasB = [tgtText.trim()];
    var keysA = parasA.map(paraKey);
    var keysB = parasB.map(paraKey);
    var ops = myersDiff(keysA, keysB);
    var segments = opsToParaSegments(parasA, parasB, ops);
    segments = detectMoves(segments);
    segments = segments.map(refineSegmentWithTokenDiff);

    var summary = { insert: 0, delete: 0, move: 0, unchanged: 0 };
    var changes = [];

    segments.forEach(function (seg) {
      if (seg.type === "equal" || seg.type === "intra") {
        summary.unchanged += contentTokenCount(seg);
        return;
      }
      if (seg.type === "insert") {
        summary.insert++;
        var idIns = "ins-" + changes.length;
        changes.push({
          id: idIns,
          type: "insert",
          snippet: snippet(seg.textB),
          side: "tgt"
        });
        seg.changeId = idIns;
        return;
      }
      if (seg.type === "delete") {
        summary.delete++;
        var idDel = "del-" + changes.length;
        changes.push({
          id: idDel,
          type: "delete",
          snippet: snippet(seg.textA),
          side: "src"
        });
        seg.changeId = idDel;
        return;
      }
      if (seg.type === "move") {
        summary.move++;
        changes.push({
          id: seg.id,
          type: "move",
          snippet: snippet(seg.textA),
          side: "both"
        });
      }
    });

    return {
      segments: segments,
      summary: summary,
      changes: changes
    };
  }

  function joinTokens(toks) {
    var out = "";
    for (var i = 0; i < toks.length; i++) {
      var tok = toks[i];
      if (i > 0 && tok.t !== "sym" && toks[i - 1].t !== "sym") {
        out += " ";
      }
      out += tok.v;
    }
    return out;
  }

  global.CallTheGapsDiff = {
    tokenize: tokenize,
    compareTexts: compareTexts,
    joinTokens: joinTokens,
    MOVE_MIN_TOKENS: MOVE_MIN_TOKENS,
    MOVE_MIN_SIMILARITY: MOVE_MIN_SIMILARITY,
    MOVE_MAX_LEN_RATIO: MOVE_MAX_LEN_RATIO
  };
})(typeof window !== "undefined" ? window : globalThis);
