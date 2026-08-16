/* CodeVault front-end helpers (plain ES5, no dependencies). */
(function () {
  "use strict";

  /* ---- Copy buttons -------------------------------------------------- */

  function markCopied(btn) {
    var original = btn.textContent;
    btn.textContent = "Copied!";
    btn.className = btn.className + " copied";
    window.setTimeout(function () {
      btn.textContent = original;
      btn.className = btn.className.replace(/\s*copied/, "");
    }, 1500);
  }

  function fallbackCopy(text, btn) {
    var area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.focus();
    area.select();
    try {
      document.execCommand("copy");
      markCopied(btn);
    } catch (err) {
      window.alert("Copy failed - select the text manually.");
    }
    document.body.removeChild(area);
  }

  function copyText(text, btn) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () { markCopied(btn); },
        function () { fallbackCopy(text, btn); }
      );
    } else {
      fallbackCopy(text, btn);
    }
  }

  function initCopyButtons() {
    var buttons = document.querySelectorAll("[data-copy-target]");
    var i;
    for (i = 0; i < buttons.length; i++) {
      (function (btn) {
        btn.addEventListener("click", function () {
          var target = document.getElementById(btn.getAttribute("data-copy-target"));
          if (target) {
            copyText(target.textContent, btn);
          }
        });
      })(buttons[i]);
    }
  }

  /* ---- Clipboard-paste / drag-drop screenshot upload ------------------ */

  function setFileInput(input, file) {
    if (typeof DataTransfer === "undefined") {
      return false;
    }
    try {
      var dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      return true;
    } catch (err) {
      return false;
    }
  }

  function showPreview(zone, file) {
    var old = zone.querySelector("img");
    if (old) {
      zone.removeChild(old);
    }
    var img = document.createElement("img");
    img.alt = "preview";
    var reader = new FileReader();
    reader.onload = function (ev) {
      img.src = ev.target.result;
    };
    reader.readAsDataURL(file);
    zone.appendChild(img);
    zone.className = "dropzone armed";
    var label = zone.querySelector(".dz-label");
    if (label) {
      label.textContent = "Image ready: " + (file.name || "pasted-screenshot.png");
    }
  }

  function acceptImage(zone, input, file) {
    if (!file || file.type.indexOf("image/") !== 0) {
      return;
    }
    var named = file;
    if (!file.name || file.name === "image.png") {
      try {
        named = new File([file], "screenshot-" + Date.now() + ".png", { type: file.type });
      } catch (err) {
        named = file;
      }
    }
    if (setFileInput(input, named)) {
      showPreview(zone, named);
    } else {
      var label = zone.querySelector(".dz-label");
      if (label) {
        label.textContent = "Paste not supported in this browser - use the file picker below.";
      }
    }
  }

  function initDropzone() {
    var zone = document.getElementById("dropzone");
    var input = document.getElementById("id_upload");
    if (!zone || !input) {
      return;
    }

    document.addEventListener("paste", function (e) {
      var items = e.clipboardData && e.clipboardData.items;
      if (!items) {
        return;
      }
      var i;
      for (i = 0; i < items.length; i++) {
        if (items[i].type.indexOf("image/") === 0) {
          e.preventDefault();
          acceptImage(zone, input, items[i].getAsFile());
          return;
        }
      }
    });

    zone.addEventListener("dragover", function (e) {
      e.preventDefault();
      zone.className = "dropzone armed";
    });
    zone.addEventListener("dragleave", function () {
      if (!zone.querySelector("img")) {
        zone.className = "dropzone";
      }
    });
    zone.addEventListener("drop", function (e) {
      e.preventDefault();
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
        acceptImage(zone, input, e.dataTransfer.files[0]);
      }
    });

    input.addEventListener("change", function () {
      if (input.files && input.files.length) {
        showPreview(zone, input.files[0]);
      }
    });
  }

  /* ---- Show/hide form fields depending on item kind -------------------- */

  function initKindToggle() {
    var kindSelect = document.getElementById("id_kind");
    if (!kindSelect) {
      return;
    }

    function fieldRow(id) {
      var el = document.getElementById(id);
      if (!el) {
        return null;
      }
      var node = el;
      while (node && node.tagName !== "P" && node !== document.body) {
        node = node.parentNode;
      }
      return node === document.body ? null : node;
    }

    function apply() {
      var kind = kindSelect.value;
      var zone = document.getElementById("dropzone");
      var contentRow = fieldRow("id_content");
      var languageRow = fieldRow("id_language");
      var uploadRow = fieldRow("id_upload");

      if (zone) { zone.style.display = kind === "image" ? "" : "none"; }
      if (contentRow) { contentRow.style.display = kind === "image" ? "none" : ""; }
      if (languageRow) { languageRow.style.display = kind === "code" ? "" : "none"; }
      if (uploadRow) { uploadRow.style.display = kind === "code" ? "none" : ""; }
    }

    kindSelect.addEventListener("change", apply);
    apply();
  }

  document.addEventListener("DOMContentLoaded", function () {
    initCopyButtons();
    initDropzone();
    initKindToggle();
  });
})();
