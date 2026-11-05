/**
 * Call the Gaps — client-side text diff (paragraph Myers/LCS, token pass on
 * fuzzy paragraphs, move relabelling). Soft-wrapped PDF lines are joined
 * before the paragraph pass. Move pass thresholds (tune on desk):
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
    /* Latin keys fold case so desk diffs ignore capitalisation-only edits. */
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

  function hasSentenceEnd(s) {
    return /[.!?。！？…]["'”’)\]]*$/.test(s);
  }

  function startsLowerContinuation(s) {
    return /^[a-z]/.test(s);
  }

  function isShortHeading(s) {
    if (!s || hasSentenceEnd(s)) return false;
    var cjk = (s.match(/[\u3400-\u9FFF\uF900-\uFAFF]/g) || []).length;
    if (cjk > 0 && cjk <= 12 && s.length < 40) return true;
    var words = s.split(/\s+/).filter(Boolean);
    return s.length < 48 && words.length <= 8;
  }

  function shouldJoinSoftWrap(prev, next) {
    if (!prev || !next) return false;
    if (startsLowerContinuation(next)) return true;
    if (/[,;:，；、]$/.test(prev)) return true;
    if (/[-\u2010-\u2015]$/.test(prev)) return true;
    if (hasSentenceEnd(prev)) return false;
    if (isShortHeading(prev) && /^[A-Z\u3400-\u9FFF\uF900-\uFAFF]/.test(next)) return false;
    return prev.length >= 40;
  }

  function splitParagraphs(text) {
    var normalised = String(text || "").replace(/\r\n/g, "\n").replace(/[ \t]+\n/g, "\n");
    if (!normalised.trim()) return [];
    var lines = normalised.split("\n");
    var blocks = [];
    var buf = "";
    function flush() {
      var t = buf.replace(/\s+/g, " ").trim();
      if (t) blocks.push(t);
      buf = "";
    }
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].replace(/\s+/g, " ").trim();
      if (!line) {
        flush();
        continue;
      }
      if (!buf) {
        buf = line;
        continue;
      }
      if (shouldJoinSoftWrap(buf, line)) {
        buf += " " + line;
      } else {
        flush();
        buf = line;
      }
    }
    flush();
    return blocks;
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
        var eqIdxA = [];
        var eqIdxB = [];
        while (i < ops.length && ops[i].type === "equal") {
          eqA.push(parasA[ops[i].ai]);
          eqB.push(parasB[ops[i].bi]);
          eqIdxA.push(ops[i].ai);
          eqIdxB.push(ops[i].bi);
          i++;
        }
        for (var j = 0; j < eqA.length; j++) {
          segments.push({
            type: "equal",
            textA: eqA[j],
            textB: eqB[j],
            idxA: eqIdxA[j],
            idxB: eqIdxB[j]
          });
        }
        continue;
      }
      if (ops[i].type === "delete") {
        var del = [];
        var delIdx = [];
        while (i < ops.length && ops[i].type === "delete") {
          del.push(parasA[ops[i].ai]);
          delIdx.push(ops[i].ai);
          i++;
        }
        del.forEach(function (p, di) {
          segments.push({ type: "delete", textA: p, textB: "", idxA: delIdx[di] });
        });
        continue;
      }
      var ins = [];
      var insIdx = [];
      while (i < ops.length && ops[i].type === "insert") {
        ins.push(parasB[ops[i].bi]);
        insIdx.push(ops[i].bi);
        i++;
      }
      ins.forEach(function (p, ii) {
        segments.push({ type: "insert", textA: "", textB: p, idxB: insIdx[ii] });
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
    if (seg.textA === seg.textB) return seg;
    var tokensA = tokenize(seg.textA);
    var tokensB = tokenize(seg.textB);
    var packA = contentMaps(tokensA);
    var packB = contentMaps(tokensB);
    var contentA = packA.map.map(function (i) { return tokensA[i]; });
    var contentB = packB.map.map(function (i) { return tokensB[i]; });
    var ops = myersDiff(packA.keys, packB.keys);
    var inner = opsToSegments(contentA, contentB, ops);
    return {
      type: "intra",
      textA: seg.textA,
      textB: seg.textB,
      inner: inner,
      idxA: seg.idxA,
      idxB: seg.idxB
    };
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
          textB: segIns.textB,
          idxA: segDel.idxA,
          idxB: segIns.idxB
        };
        segments[best.ins.idx] = { type: "move-gap", hide: true };
      }
    });

    return segments.filter(function (s) { return !s.hide; });
  }

  function nextMoveId(segments) {
    var max = 0;
    segments.forEach(function (s) {
      if (s.id && /^mv-\d+$/.test(s.id)) {
        var n = parseInt(s.id.slice(3), 10);
        if (n > max) max = n;
      }
    });
    return max + 1;
  }

  function pairCrosses(a, b) {
    if (a.idxA == null || a.idxB == null || b.idxA == null || b.idxB == null) return false;
    var dA = a.idxA - b.idxA;
    var dB = a.idxB - b.idxB;
    return dA !== 0 && dB !== 0 && dA > 0 !== dB > 0;
  }

  function adjacentAmongMatched(seg, other, matched) {
    var aLo = Math.min(seg.idxA, other.idxA);
    var aHi = Math.max(seg.idxA, other.idxA);
    var bLo = Math.min(seg.idxB, other.idxB);
    var bHi = Math.max(seg.idxB, other.idxB);
    for (var i = 0; i < matched.length; i++) {
      var s = matched[i];
      if (s === seg || s === other) continue;
      if (s.idxA != null && s.idxA > aLo && s.idxA < aHi) return false;
      if (s.idxB != null && s.idxB > bLo && s.idxB < bHi) return false;
    }
    return true;
  }

  function asMove(seg, id) {
    return {
      type: "move",
      id: id,
      textA: seg.textA,
      textB: seg.textB,
      idxA: seg.idxA,
      idxB: seg.idxB
    };
  }

  function promotePositionalMoves(segments) {
    var nextId = nextMoveId(segments);
    var hasBlockChange = segments.some(function (s) {
      return s.type === "insert" || s.type === "delete";
    });
    if (!hasBlockChange) {
      return segments.map(function (seg) {
        if (
          seg.type === "equal" &&
          seg.idxA != null &&
          seg.idxB != null &&
          seg.idxA !== seg.idxB
        ) {
          return asMove(seg, "mv-" + nextId++);
        }
        return seg;
      });
    }
    var matched = segments.filter(function (s) {
      return s.type === "equal" || s.type === "move" || s.type === "intra";
    });
    var moves = segments.filter(function (s) { return s.type === "move"; });
    return segments.map(function (seg) {
      if (
        seg.type !== "equal" ||
        seg.idxA == null ||
        seg.idxB == null ||
        seg.idxA === seg.idxB
      ) {
        return seg;
      }
      var swap = moves.some(function (mv) {
        return pairCrosses(seg, mv) && adjacentAmongMatched(seg, mv, matched);
      });
      return swap ? asMove(seg, "mv-" + nextId++) : seg;
    });
  }

  function orderSegmentsForSide(segments, side) {
    var src = side === "src" || side === "a";
    var out = [];
    for (var i = 0; i < segments.length; i++) {
      var seg = segments[i];
      if (!seg || seg.hide) continue;
      if (src) {
        if (seg.type === "insert") continue;
        if (seg.idxA == null && !seg.textA) continue;
      } else {
        if (seg.type === "delete") continue;
        if (seg.idxB == null && !seg.textB) continue;
      }
      out.push(seg);
    }
    out.sort(function (a, b) {
      var ka = src ? a.idxA : a.idxB;
      var kb = src ? b.idxA : b.idxB;
      if (ka == null && kb == null) return 0;
      if (ka == null) return 1;
      if (kb == null) return -1;
      return ka - kb;
    });
    return out;
  }

  function sortChanges(changes) {
    changes.sort(function (a, b) {
      function key(c) {
        if (c.idxB != null) return c.idxB;
        if (c.idxA != null) return 100000 + c.idxA;
        return 200000;
      }
      var d = key(a) - key(b);
      if (d !== 0) return d;
      var rank = { move: 0, insert: 1, delete: 2 };
      return (rank[a.type] || 0) - (rank[b.type] || 0);
    });
    return changes;
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
    segments = promotePositionalMoves(segments);
    segments = segments.map(refineSegmentWithTokenDiff);

    var summary = { insert: 0, delete: 0, move: 0, unchanged: 0 };
    var changes = [];

    segments.forEach(function (seg) {
      if (seg.type === "equal") {
        summary.unchanged += contentTokenCount(seg);
        return;
      }
      if (seg.type === "intra" && seg.inner) {
        seg.inner.forEach(function (part) {
          if (part.type === "equal") {
            summary.unchanged += part.a.filter(function (t) { return t.t !== "ws"; }).length;
          } else if (part.type === "insert") {
            summary.insert++;
            var idIns = "ins-" + changes.length;
            part.changeId = idIns;
            changes.push({
              id: idIns,
              type: "insert",
              snippet: snippet(joinTokens(part.b)),
              side: "tgt",
              idxA: seg.idxA,
              idxB: seg.idxB
            });
          } else if (part.type === "delete") {
            summary.delete++;
            var idDel = "del-" + changes.length;
            part.changeId = idDel;
            changes.push({
              id: idDel,
              type: "delete",
              snippet: snippet(joinTokens(part.a)),
              side: "src",
              idxA: seg.idxA,
              idxB: seg.idxB
            });
          }
        });
        return;
      }
      if (seg.type === "insert") {
        summary.insert++;
        var idIns = "ins-" + changes.length;
        changes.push({
          id: idIns,
          type: "insert",
          snippet: snippet(seg.textB),
          side: "tgt",
          idxA: seg.idxA,
          idxB: seg.idxB
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
          side: "src",
          idxA: seg.idxA,
          idxB: seg.idxB
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
          side: "both",
          idxA: seg.idxA,
          idxB: seg.idxB
        });
      }
    });

    sortChanges(changes);

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
    splitParagraphs: splitParagraphs,
    shouldJoinSoftWrap: shouldJoinSoftWrap,
    orderSegmentsForSide: orderSegmentsForSide,
    MOVE_MIN_TOKENS: MOVE_MIN_TOKENS,
    MOVE_MIN_SIMILARITY: MOVE_MIN_SIMILARITY,
    MOVE_MAX_LEN_RATIO: MOVE_MAX_LEN_RATIO
  };
})(typeof window !== "undefined" ? window : globalThis);
