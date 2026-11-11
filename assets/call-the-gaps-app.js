(function () {
  "use strict";

  var readerSrc = {
    pdf: "/assets/pdfjs/pdf.min.js",
    docx: "/assets/mammoth/mammoth.browser.min.js"
  };
  var readerLoad = {};
  function ensureReader(kind) {
    if (kind === "pdf" && typeof pdfjsLib !== "undefined") {
      pdfjsLib.GlobalWorkerOptions.workerSrc = "/assets/pdfjs/pdf.worker.min.js";
      return Promise.resolve();
    }
    if (kind === "docx" && typeof mammoth !== "undefined") return Promise.resolve();
    var src = readerSrc[kind];
    var missing = kind === "docx" ? "word-reader-missing" : "reader-missing";
    if (!src) return Promise.reject(new Error(missing));
    if (!readerLoad[kind]) {
      readerLoad[kind] = new Promise(function (resolve, reject) {
        var script = document.createElement("script");
        script.src = src;
        script.async = true;
        script.onload = function () { resolve(); };
        script.onerror = function () {
          readerLoad[kind] = null;
          reject(new Error(missing));
        };
        document.head.appendChild(script);
      });
    }
    return readerLoad[kind].then(function () {
      if (kind === "pdf") {
        if (typeof pdfjsLib === "undefined") throw new Error("reader-missing");
        pdfjsLib.GlobalWorkerOptions.workerSrc = "/assets/pdfjs/pdf.worker.min.js";
        return;
      }
      if (typeof mammoth === "undefined") throw new Error("word-reader-missing");
    });
  }

  var $ = function (id) { return document.getElementById(id); };
  var joinTokens = CallTheGapsDiff.joinTokens;

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  var SIDES = ["src", "tgt"];
  var jobs = { src: 0, tgt: 0 };
  var texts = { src: "", tgt: "" };
  var names = { src: "", tgt: "" };
  var statusText = { src: "", tgt: "" };
  var statusError = { src: false, tgt: false };
  var structure = { src: null, tgt: null };
  var lastResult = null;
  var activeFilter = "all";
  var CHOOSE_LABEL = "Choose a PDF or Word file";
  var syncLocked = false;
  var syncLockTimer = null;
  var jumpClearTimer = null;
  var jumpTypeCursor = { type: "", index: -1 };

  function structureCountLabel(meta) {
    if (!meta) return "";
    if (meta.measure === "pages") {
      return meta.count + (meta.count === 1 ? " page" : " pages");
    }
    return meta.count + (meta.count === 1 ? " paragraph" : " paragraphs");
  }

  function paintStructureNote() {
    var noteEl = $("structureNote");
    if (!noteEl) return;
    var a = structure.src;
    var b = structure.tgt;
    var ready =
      texts.src.trim() &&
      texts.tgt.trim() &&
      !statusError.src &&
      !statusError.tgt &&
      a &&
      b;
    if (!ready || (a.measure === b.measure && a.count === b.count)) {
      noteEl.hidden = true;
      noteEl.textContent = "";
      return;
    }
    noteEl.textContent =
      "Precedent: " +
      structureCountLabel(a) +
      ". Later file: " +
      structureCountLabel(b) +
      ". Unequal pagination or layout between languages and formats is normal on HK bilingual packs — the check compares the full text of both files, not page by page.";
    noteEl.hidden = false;
  }

  function isCjkChar(ch) {
    return /[\u3400-\u9FFF\uF900-\uFAFF]/.test(ch);
  }

  function itemsToText(items) {
    var out = "";
    var lastY = null;
    var lastEnd = null;
    var lastChar = "";
    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      var str = item.str || "";
      if (!str) continue;
      var tr = item.transform || [0, 0, 0, 0, 0, 0];
      var x = tr[4];
      var y = tr[5];
      var size = Math.abs(tr[3]) || item.height || 10;
      if (lastY !== null && Math.abs(y - lastY) > size * 0.8) {
        out += "\n";
        lastEnd = null;
        lastChar = "\n";
      }
      if (lastEnd !== null && out && !/\s$/.test(out)) {
        var gap = x - lastEnd;
        var prevCjk = isCjkChar(lastChar);
        var nextCjk = isCjkChar(str.charAt(0));
        if (!prevCjk && !nextCjk && gap > size * 0.25) out += " ";
      }
      out += str;
      lastY = y;
      lastEnd = x + (item.width || 0);
      lastChar = str.charAt(str.length - 1);
      if (item.hasEOL) {
        out += "\n";
        lastY = null;
        lastEnd = null;
        lastChar = "\n";
      }
    }
    return out.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n");
  }

  function isPdf(file) {
    var type = (file.type || "").toLowerCase();
    var name = (file.name || "").toLowerCase();
    return type === "application/pdf" || type === "application/x-pdf" || /\.pdf$/.test(name);
  }
  function isDocx(file) {
    var type = (file.type || "").toLowerCase();
    var name = (file.name || "").toLowerCase();
    return type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" || /\.docx$/.test(name);
  }
  function isLegacyDoc(file) {
    var type = (file.type || "").toLowerCase();
    var name = (file.name || "").toLowerCase();
    if (/\.docx$/.test(name)) return false;
    if (/\.doc$/.test(name)) return true;
    return type === "application/msword";
  }
  function fileKind(file) {
    if (isLegacyDoc(file)) return "legacy-doc";
    if (isPdf(file)) return "pdf";
    if (isDocx(file)) return "docx";
    return "unsupported";
  }
  function countWordParagraphs(text) {
    return text.split(/\n+/).filter(function (s) { return s.trim(); }).length;
  }
  function friendlyError(err, kind) {
    var name = err && err.name;
    var msg = err && err.message;
    if (msg === "empty-file") return "This file is empty.";
    if (msg === "legacy-doc") return "Legacy .doc files are not supported. Save as .docx and try again.";
    if (kind === "docx" || msg === "word-reader-missing") {
      if (msg === "word-reader-missing") return "The Word reader did not load. Reload the page and try again.";
      if (msg && /zip file|central directory|end of central directory|invalid signature/i.test(msg)) {
        return "This file is not a readable Word document (.docx).";
      }
      return "Could not read this Word file. Try another .docx.";
    }
    if (name === "PasswordException") return "This PDF is password-protected. Remove the password and upload it again.";
    if (name === "InvalidPDFException") return "This file is not a readable PDF.";
    if (msg === "reader-missing") return "The PDF reader did not load. Reload the page and try again.";
    return "Could not read this PDF. Try another file.";
  }
  function extractPdfText(file, onPage) {
    if (typeof pdfjsLib === "undefined") return Promise.reject(new Error("reader-missing"));
    return file.arrayBuffer().then(function (buf) {
      var task = pdfjsLib.getDocument({
        data: new Uint8Array(buf),
        cMapUrl: "/assets/pdfjs/cmaps/",
        cMapPacked: true,
        standardFontDataUrl: "/assets/pdfjs/standard_fonts/",
        disableFontFace: true,
        isEvalSupported: false
      });
      return task.promise.then(function (pdf) {
        var pages = pdf.numPages;
        var chain = Promise.resolve([]);
        for (var n = 1; n <= pages; n++) {
          (function (pageNo) {
            chain = chain.then(function (chunks) {
              if (onPage) onPage(pageNo, pages);
              return pdf.getPage(pageNo).then(function (page) {
                return page.getTextContent().then(function (content) {
                  chunks.push(itemsToText(content.items));
                  return chunks;
                });
              });
            });
          })(n);
        }
        return chain.then(function (chunks) {
          pdf.destroy();
          return { text: chunks.join("\n\n"), pages: pages };
        }, function (err) {
          pdf.destroy();
          throw err;
        });
      });
    });
  }
  function extractDocxText(file) {
    if (typeof mammoth === "undefined") return Promise.reject(new Error("word-reader-missing"));
    if (!file.size) return Promise.reject(new Error("empty-file"));
    return file.arrayBuffer().then(function (buf) {
      return mammoth.extractRawText({ arrayBuffer: buf }).then(function (result) {
        var text = result.value || "";
        return { text: text, paragraphs: countWordParagraphs(text) };
      });
    });
  }

  function paintStatus() {
    SIDES.forEach(function (side) {
      var el = $(side + "Status");
      el.textContent = statusText[side];
      el.className = "file-status" + (statusError[side] ? " is-error" : "");
      $(side + "Name").textContent = names[side] || CHOOSE_LABEL;
      $(side + "Count").textContent = texts[side].trim() ? "loaded" : "";
    });
    paintStructureNote();
  }

  function renderInner(inner, side) {
    var html = "";
    inner.forEach(function (part) {
      if (part.type === "equal") {
        html += esc(joinTokens(side === "src" ? part.a : part.b));
      } else if (part.type === "delete" && side === "src") {
        html +=
          '<mark class="mark-delete" data-change-id="' +
          esc(part.changeId || "") +
          '">' +
          esc(joinTokens(part.a)) +
          "</mark>";
      } else if (part.type === "insert" && side === "tgt") {
        html +=
          '<mark class="mark-insert" data-change-id="' +
          esc(part.changeId || "") +
          '">' +
          esc(joinTokens(part.b)) +
          "</mark>";
      }
    });
    return html;
  }

  function wrapBlock(innerHtml) {
    if (!innerHtml) return "";
    return '<p class="diff-block">' + innerHtml + "</p>";
  }

  function renderPane(segments, side) {
    var html = "";
    var ordered = CallTheGapsDiff.orderSegmentsForSide
      ? CallTheGapsDiff.orderSegmentsForSide(segments, side)
      : segments;
    ordered.forEach(function (seg) {
      if (seg.type === "equal") {
        var t = side === "src" ? seg.textA : seg.textB;
        html += wrapBlock(esc(t));
        return;
      }
      if (seg.type === "intra") {
        html += wrapBlock(renderInner(seg.inner, side));
        return;
      }
      if (seg.type === "insert") {
        if (side === "tgt") {
          html +=
            wrapBlock(
              '<mark class="mark-insert" data-change-id="' +
                esc(seg.changeId) +
                '">' +
                esc(seg.textB) +
                "</mark>"
            );
        }
        return;
      }
      if (seg.type === "delete") {
        if (side === "src") {
          html +=
            wrapBlock(
              '<mark class="mark-delete" data-change-id="' +
                esc(seg.changeId) +
                '">' +
                esc(seg.textA) +
                "</mark>"
            );
        }
        return;
      }
      if (seg.type === "move") {
        var text = side === "src" ? seg.textA : seg.textB;
        html +=
          wrapBlock(
            '<mark class="mark-move" data-change-id="' +
              esc(seg.id) +
              '" tabindex="0" role="button">' +
              esc(text) +
              "</mark>"
          );
      }
    });
    return html || '<p class="empty">No text on this side.</p>';
  }

  function summaryHtml(summary) {
    var h = '<div class="summary" id="summaryStrip">';
    h += chipButton("insert", summary.insert, summary.insert + " insert" + (summary.insert === 1 ? "" : "s"));
    h += chipButton("delete", summary.delete, summary.delete + " delete" + (summary.delete === 1 ? "" : "s"));
    h += chipButton("move", summary.move, summary.move + " move" + (summary.move === 1 ? "" : "s"));
    h += '<span class="chip chip--ok">' + summary.unchanged + " unchanged tokens</span>";
    h += "</div>";
    return h;
  }

  function chipButton(type, count, label) {
    return (
      '<button type="button" class="chip chip--' +
      type +
      '" data-jump-type="' +
      type +
      '"' +
      (count ? "" : " disabled") +
      ">" +
      label +
      "</button>"
    );
  }

  function errorStripHtml(changes) {
    if (!changes.length) return "";
    var h =
      '<div class="error-strip" id="errorStrip" role="list" aria-label="Typed changes">';
    changes.forEach(function (c) {
      h +=
        '<button type="button" class="chip chip--' +
        c.type +
        ' error-chip" role="listitem" data-change-id="' +
        esc(c.id) +
        '" data-change-type="' +
        c.type +
        '"><span class="error-chip__type">' +
        c.type +
        "</span> " +
        esc(c.snippet) +
        "</button>";
    });
    h += "</div>";
    return h;
  }

  function railFiltersHtml() {
    var types = ["all", "insert", "delete", "move"];
    var h = '<div class="rail-filters" role="group" aria-label="Filter changes">';
    types.forEach(function (t) {
      var label = t === "all" ? "All" : t.charAt(0).toUpperCase() + t.slice(1);
      h +=
        '<button type="button" class="chip rail-filter' +
        (activeFilter === t ? " is-on" : "") +
        '" data-filter="' +
        t +
        '">' +
        label +
        "</button>";
    });
    h += "</div>";
    return h;
  }

  function railListHtml(changes) {
    if (!changes.length) {
      return '<p class="empty rail-empty">No typed changes — text aligns at paragraph level.</p>';
    }
    var h = '<ul class="rail-list">';
    changes.forEach(function (c) {
      h +=
        '<li><button type="button" class="rail-item" data-change-id="' +
        esc(c.id) +
        '" data-change-type="' +
        c.type +
        '"><span class="rail-item__type">' +
        c.type +
        '</span><span class="rail-item__snippet">' +
        esc(c.snippet) +
        "</span></button></li>";
    });
    h += "</ul>";
    return h;
  }

  function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function lockScrollSync(ms) {
    syncLocked = true;
    if (syncLockTimer) clearTimeout(syncLockTimer);
    syncLockTimer = setTimeout(function () {
      syncLocked = false;
      syncLockTimer = null;
    }, ms || 700);
  }

  function attrEscape(id) {
    if (typeof CSS !== "undefined" && CSS.escape) return CSS.escape(id);
    return String(id).replace(/"/g, '\\"');
  }

  function scrollContainerToEl(container, el, center) {
    if (!container || !el) return;
    var cRect = container.getBoundingClientRect();
    var eRect = el.getBoundingClientRect();
    var delta = 0;
    if (center) {
      delta = eRect.top - cRect.top - container.clientHeight / 2 + eRect.height / 2;
    } else if (eRect.top < cRect.top) {
      delta = eRect.top - cRect.top;
    } else if (eRect.bottom > cRect.bottom) {
      delta = eRect.bottom - cRect.bottom;
    }
    if (!delta) return;
    var max = container.scrollHeight - container.clientHeight;
    if (max < 0) max = 0;
    var top = container.scrollTop + delta;
    if (top < 0) top = 0;
    if (top > max) top = max;
    if (typeof container.scrollTo === "function") {
      container.scrollTo({
        top: top,
        behavior: prefersReducedMotion() ? "auto" : "smooth"
      });
    } else {
      container.scrollTop = top;
    }
  }

  function bindScrollSync() {
    var srcView = $("srcView");
    var tgtView = $("tgtView");
    if (!srcView || !tgtView) return;
    var syncing = false;
    function sync(from, to) {
      if (syncLocked || syncing) return;
      syncing = true;
      var maxFrom = from.scrollHeight - from.clientHeight;
      var maxTo = to.scrollHeight - to.clientHeight;
      var ratio = maxFrom > 0 ? from.scrollTop / maxFrom : 0;
      to.scrollTop = ratio * (maxTo > 0 ? maxTo : 0);
      syncing = false;
    }
    srcView.addEventListener("scroll", function () { sync(srcView, tgtView); });
    tgtView.addEventListener("scroll", function () { sync(tgtView, srcView); });
  }

  function clearJumpHighlight() {
    document.querySelectorAll(".is-active").forEach(function (el) {
      el.classList.remove("is-active");
    });
    document.querySelectorAll(".is-current").forEach(function (el) {
      el.classList.remove("is-current");
      if (el.hasAttribute("aria-current")) el.removeAttribute("aria-current");
    });
  }

  function jumpToChange(id) {
    if (!id) return;
    var safe = attrEscape(id);
    clearJumpHighlight();
    if (jumpClearTimer) clearTimeout(jumpClearTimer);

    var marks = document.querySelectorAll('.diff-pane__body [data-change-id="' + safe + '"]');
    marks.forEach(function (m) {
      m.classList.add("is-active");
    });

    document.querySelectorAll('[data-change-id="' + safe + '"]').forEach(function (el) {
      if (el.classList.contains("rail-item") || el.classList.contains("error-chip")) {
        el.classList.add("is-current");
        el.setAttribute("aria-current", "true");
      }
    });

    lockScrollSync(prefersReducedMotion() ? 50 : 700);

    var panes = document.querySelector(".diff-panes");
    if (panes) {
      var paneRect = panes.getBoundingClientRect();
      var navOffset = 88;
      if (paneRect.top < navOffset || paneRect.bottom > window.innerHeight) {
        panes.scrollIntoView({
          block: "nearest",
          behavior: prefersReducedMotion() ? "auto" : "smooth"
        });
      }
    }

    marks.forEach(function (mark) {
      var pane = mark.closest(".diff-pane__body");
      scrollContainerToEl(pane, mark, true);
    });

    var rail = $("changeRail");
    var railBtn = document.querySelector('.rail-item[data-change-id="' + safe + '"]');
    if (rail && railBtn) scrollContainerToEl(rail, railBtn, false);

    var strip = $("errorStrip");
    var chip = document.querySelector('.error-chip[data-change-id="' + safe + '"]');
    if (strip && chip) scrollContainerToEl(strip, chip, false);

    jumpClearTimer = setTimeout(function () {
      marks.forEach(function (m) { m.classList.remove("is-active"); });
    }, 2400);
  }

  function jumpToType(type) {
    if (!type || type === "all") return;
    var items = document.querySelectorAll('.error-chip[data-change-type="' + type + '"], .rail-item[data-change-type="' + type + '"]');
    var seen = [];
    var unique = [];
    items.forEach(function (el) {
      var id = el.getAttribute("data-change-id");
      if (!id || seen.indexOf(id) !== -1) return;
      seen.push(id);
      unique.push(el);
    });
    if (!unique.length) return;
    if (jumpTypeCursor.type !== type) {
      jumpTypeCursor.type = type;
      jumpTypeCursor.index = -1;
    }
    jumpTypeCursor.index = (jumpTypeCursor.index + 1) % unique.length;
    jumpToChange(unique[jumpTypeCursor.index].getAttribute("data-change-id"));
  }

  function applyFilter() {
    document.querySelectorAll(".rail-item").forEach(function (btn) {
      var type = btn.getAttribute("data-change-type");
      btn.parentElement.hidden = activeFilter !== "all" && activeFilter !== type;
    });
    document.querySelectorAll(".error-chip").forEach(function (btn) {
      var type = btn.getAttribute("data-change-type");
      btn.hidden = activeFilter !== "all" && activeFilter !== type;
    });
    document.querySelectorAll(".rail-filter").forEach(function (btn) {
      btn.classList.toggle("is-on", btn.getAttribute("data-filter") === activeFilter);
    });
  }

  function bindResultsUi() {
    var el = $("results");
    if (!el) return;
    el.addEventListener("click", function (e) {
      var filterBtn = e.target.closest(".rail-filter");
      if (filterBtn) {
        activeFilter = filterBtn.getAttribute("data-filter") || "all";
        applyFilter();
        return;
      }
      var typeChip = e.target.closest("[data-jump-type]");
      if (typeChip && !typeChip.disabled) {
        jumpToType(typeChip.getAttribute("data-jump-type"));
        return;
      }
      var item = e.target.closest(".rail-item, .error-chip");
      if (item) {
        jumpTypeCursor.type = item.getAttribute("data-change-type") || "";
        jumpTypeCursor.index = -1;
        jumpToChange(item.getAttribute("data-change-id"));
      }
    });
    document.querySelectorAll(".mark-move").forEach(function (mark) {
      mark.addEventListener("click", function () {
        jumpToChange(mark.getAttribute("data-change-id"));
      });
    });
    bindScrollSync();
  }

  function run() {
    paintStatus();
    var el = $("results");
    var busy = statusText.src.indexOf("Reading") === 0 || statusText.tgt.indexOf("Reading") === 0;
    if (busy) {
      el.innerHTML = '<p class="empty">Reading the file…</p>';
      lastResult = null;
      return;
    }
    if (!texts.src.trim() || !texts.tgt.trim()) {
      var msg = "Upload the precedent and the later file (PDF or Word) to compare.";
      if ((texts.src.trim() && !texts.tgt.trim()) || (!texts.src.trim() && texts.tgt.trim())) {
        msg = texts.src.trim() ? "Upload the later file to compare." : "Upload the precedent to compare.";
      }
      if (statusError.src || statusError.tgt) {
        msg = "Choose a readable PDF or Word (.docx) file for both the precedent and the later file to compare.";
      }
      el.innerHTML = '<p class="empty">' + msg + "</p>";
      lastResult = null;
      return;
    }

    lastResult = CallTheGapsDiff.compareTexts(texts.src, texts.tgt);
    var r = lastResult;
    var h = summaryHtml(r.summary);
    h += '<div class="gap-layout">';
    h += '<aside class="change-rail" id="changeRail" aria-label="Changes">';
    h += railFiltersHtml();
    h += railListHtml(r.changes);
    h += "</aside>";
    h += '<div class="diff-panes">';
    h += '<div class="diff-pane"><h2 class="diff-pane__title">Precedent</h2><div class="diff-pane__body" id="srcView">' + renderPane(r.segments, "src") + "</div></div>";
    h += '<div class="diff-pane"><h2 class="diff-pane__title">Later file</h2><div class="diff-pane__body" id="tgtView">' + renderPane(r.segments, "tgt") + "</div></div>";
    h += "</div></div>";
    h += errorStripHtml(r.changes);
    el.innerHTML = h;
    bindResultsUi();
    applyFilter();
  }

  function takeFile(side, file) {
    var job = ++jobs[side];
    texts[side] = "";
    structure[side] = null;
    statusError[side] = false;
    if (!file) {
      names[side] = "";
      statusText[side] = "";
      run();
      return;
    }
    names[side] = file.name;
    if (!file.size) {
      statusError[side] = true;
      statusText[side] = "This file is empty.";
      run();
      return;
    }
    var kind = fileKind(file);
    if (kind === "legacy-doc") {
      statusError[side] = true;
      statusText[side] = friendlyError(new Error("legacy-doc"), "docx");
      run();
      return;
    }
    if (kind === "unsupported") {
      statusError[side] = true;
      statusText[side] = "Choose a PDF or Word (.docx) file.";
      run();
      return;
    }
    statusText[side] = kind === "pdf" ? "Reading PDF…" : "Reading Word document…";
    run();
    ensureReader(kind).then(function () {
      if (job !== jobs[side]) return null;
      if (kind === "pdf") {
        return extractPdfText(file, function (pageNo, total) {
          if (job !== jobs[side]) return;
          statusText[side] = "Reading page " + pageNo + " of " + total + "…";
          paintStatus();
          $("results").innerHTML = '<p class="empty">Reading the file…</p>';
        });
      }
      return extractDocxText(file);
    }).then(function (result) {
      if (job !== jobs[side] || result == null) return;
      if (!result.text.trim()) {
        statusError[side] = true;
        if (kind === "pdf") {
          statusText[side] = "No selectable text in this PDF. Scanned or image-only files are not covered.";
        } else {
          statusText[side] = "No readable text in this Word file.";
        }
        texts[side] = "";
      } else {
        statusError[side] = false;
        if (kind === "pdf") {
          statusText[side] = result.pages + (result.pages === 1 ? " page" : " pages");
          structure[side] = { measure: "pages", count: result.pages };
        } else {
          var p = result.paragraphs;
          statusText[side] = p + (p === 1 ? " paragraph" : " paragraphs");
          structure[side] = { measure: "paragraphs", count: p };
        }
        texts[side] = result.text;
      }
      run();
    }, function (err) {
      if (job !== jobs[side]) return;
      statusError[side] = true;
      statusText[side] = friendlyError(err, kind);
      texts[side] = "";
      run();
    });
  }

  function bindSide(side) {
    var input = $(side + "File");
    var drop = $(side + "Drop");
    input.addEventListener("change", function () {
      takeFile(side, input.files && input.files[0] ? input.files[0] : null);
    });
    ["dragenter", "dragover"].forEach(function (type) {
      drop.addEventListener(type, function (e) {
        e.preventDefault();
        drop.classList.add("is-drag");
      });
    });
    drop.addEventListener("dragleave", function () { drop.classList.remove("is-drag"); });
    drop.addEventListener("drop", function (e) {
      e.preventDefault();
      drop.classList.remove("is-drag");
      var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) takeFile(side, file);
    });
  }

  bindSide("src");
  bindSide("tgt");

  $("btnClear").addEventListener("click", function () {
    jobs.src += 1;
    jobs.tgt += 1;
    activeFilter = "all";
    jumpTypeCursor = { type: "", index: -1 };
    SIDES.forEach(function (side) {
      texts[side] = "";
      names[side] = "";
      statusText[side] = "";
      statusError[side] = false;
      structure[side] = null;
      $(side + "File").value = "";
    });
    run();
    $("srcFile").focus();
  });

  if (typeof window !== "undefined") {
    window.CallTheGaps = {
      run: run,
      takeFile: takeFile,
      jumpToChange: jumpToChange,
      setTexts: function (src, tgt) {
        texts.src = src || "";
        texts.tgt = tgt || "";
        names.src = texts.src ? "precedent.txt" : "";
        names.tgt = texts.tgt ? "newer.txt" : "";
        statusError.src = false;
        statusError.tgt = false;
        statusText.src = texts.src ? "loaded" : "";
        statusText.tgt = texts.tgt ? "loaded" : "";
        structure.src = texts.src ? { measure: "paragraphs", count: countWordParagraphs(texts.src) } : null;
        structure.tgt = texts.tgt ? { measure: "paragraphs", count: countWordParagraphs(texts.tgt) } : null;
        run();
      }
    };
  }
  run();
})();
