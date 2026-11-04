/* Mobile nav toggle. One copy for every public page that ships the menu. */
(function () {
  var nav = document.getElementById("topnav");
  var toggle = document.getElementById("nav-toggle");
  var panel = document.getElementById("mobile-panel");
  if (!nav || !toggle || !panel) return;

  var locked = false;
  var lockedScrollY = 0;
  var desktop = window.matchMedia("(min-width: 900px)");

  function freezeScroll() {
    lockedScrollY = window.scrollY || document.documentElement.scrollTop || 0;
    var root = document.documentElement;
    var previous = root.style.scrollBehavior;
    root.style.scrollBehavior = "auto";
    window.scrollTo(0, lockedScrollY);
    root.style.scrollBehavior = previous;
    locked = true;
    root.classList.add("nav-scroll-lock");
  }

  function releaseScroll() {
    if (!locked) return;
    var y = lockedScrollY;
    locked = false;
    document.documentElement.classList.remove("nav-scroll-lock");
    if (Math.abs((window.scrollY || 0) - y) > 1) {
      var root = document.documentElement;
      var previous = root.style.scrollBehavior;
      root.style.scrollBehavior = "auto";
      window.scrollTo(0, y);
      root.style.scrollBehavior = previous;
    }
  }

  function closeNav(skipRestore) {
    var wasLocked = locked;
    nav.classList.remove("is-open");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Open menu");
    panel.hidden = true;
    if (!wasLocked) return;
    if (skipRestore) {
      locked = false;
      document.documentElement.classList.remove("nav-scroll-lock");
      return;
    }
    releaseScroll();
  }

  function openNav() {
    if (desktop.matches) return;
    freezeScroll();
    panel.scrollTop = 0;
    nav.classList.add("is-open");
    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", "Close menu");
    panel.hidden = false;
  }

  toggle.addEventListener("click", function () {
    if (nav.classList.contains("is-open")) closeNav(false);
    else openNav();
  });

  panel.querySelectorAll("a").forEach(function (link) {
    link.addEventListener("click", function (e) {
      var href = link.getAttribute("href") || "";
      var hashAt = href.indexOf("#");
      var hash = hashAt >= 0 ? href.slice(hashAt + 1) : "";
      var file = (hashAt >= 0 ? href.slice(0, hashAt) : href).split("/").pop();
      var here = location.pathname.split("/").pop() || "index.html";
      if (!here) here = "index.html";
      var sameDoc = !file || file === here;
      var target = hash ? document.getElementById(hash) : null;
      /* Close the overlay first, then scroll. Hiding the panel during the
         click used to update location.hash without moving the page, so an
         in-page site-map jump from a lower section never landed. */
      if (sameDoc && target) {
        e.preventDefault();
        closeNav(true);
        if (history.replaceState) history.replaceState(null, "", "#" + hash);
        else location.hash = hash;
        target.scrollIntoView();
        return;
      }
      closeNav(true);
    });
  });

  window.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      closeNav(false);
      return;
    }
    if (!locked) return;
    var scrollKeys = {
      ArrowDown: true,
      ArrowUp: true,
      PageDown: true,
      PageUp: true,
      Home: true,
      End: true,
      " ": true
    };
    if (!scrollKeys[e.key]) return;
    var tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if ((tag === "BUTTON" || tag === "A" || tag === "SUMMARY") && e.key === " ") return;
    if (panel.contains(e.target) && (e.key === "ArrowDown" || e.key === "ArrowUp")) return;
    e.preventDefault();
  });

  var lastTouchY = 0;
  document.addEventListener("touchstart", function (e) {
    if (e.touches && e.touches[0]) lastTouchY = e.touches[0].clientY;
  }, { passive: true });

  document.addEventListener("touchmove", function (e) {
    if (!locked || !e.touches || !e.touches[0]) return;
    var y = e.touches[0].clientY;
    var dy = y - lastTouchY;
    lastTouchY = y;
    if (!panel.contains(e.target)) {
      e.preventDefault();
      return;
    }
    var max = panel.scrollHeight - panel.clientHeight;
    if (max <= 0) {
      e.preventDefault();
      return;
    }
    var atTop = panel.scrollTop <= 0;
    var atBottom = panel.scrollTop >= max - 1;
    if ((dy > 0 && atTop) || (dy < 0 && atBottom)) e.preventDefault();
  }, { passive: false });

  function onDesktopChange(event) {
    if (event.matches) closeNav(false);
  }
  if (desktop.addEventListener) desktop.addEventListener("change", onDesktopChange);
  else if (desktop.addListener) desktop.addListener(onDesktopChange);
})();
