(function () {
  "use strict";

  var chips = Array.prototype.slice.call(document.querySelectorAll("[data-type]"));
  var rows = Array.prototype.slice.call(document.querySelectorAll(".hit-row"));
  var empty = document.getElementById("empty-state");
  var countEl = document.getElementById("hit-count");
  var clearBtn = document.getElementById("filter-clear");
  var total = rows.length;

  function selectedTypes() {
    return chips
      .filter(function (chip) {
        return chip.getAttribute("aria-pressed") === "true";
      })
      .map(function (chip) {
        return chip.getAttribute("data-type");
      });
  }

  function rowTypes(row) {
    return (row.getAttribute("data-types") || "")
      .split("|")
      .map(function (s) { return s.trim(); })
      .filter(Boolean);
  }

  function applyFilter() {
    var selected = selectedTypes();
    var shown = 0;

    rows.forEach(function (row) {
      var types = rowTypes(row);
      var match =
        selected.length === 0 ||
        selected.some(function (t) {
          return types.indexOf(t) !== -1;
        });
      row.hidden = !match;
      if (match) shown += 1;
    });

    if (empty) {
      empty.hidden = shown !== 0;
    }

    if (countEl) {
      if (selected.length === 0) {
        countEl.textContent = total + " Hits on file.";
      } else if (shown === 0) {
        countEl.textContent = "0 Hits shown.";
      } else if (shown === 1) {
        countEl.textContent = "1 Hit shown.";
      } else {
        countEl.textContent = shown + " Hits shown.";
      }
    }

    if (clearBtn) {
      clearBtn.disabled = selected.length === 0;
    }
  }

  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      var pressed = chip.getAttribute("aria-pressed") === "true";
      chip.setAttribute("aria-pressed", pressed ? "false" : "true");
      applyFilter();
    });
  });

  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      chips.forEach(function (chip) {
        chip.setAttribute("aria-pressed", "false");
      });
      applyFilter();
    });
  }

  applyFilter();
})();
