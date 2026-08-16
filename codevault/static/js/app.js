/* CodeVault front-end (plain ES5; CodeMirror is self-hosted, loaded on pages that need it). */
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
            copyText(target.value !== undefined ? target.value : target.textContent, btn);
          }
        });
      })(buttons[i]);
    }
  }

  /* ---- CodeMirror ---------------------------------------------------- */

  var MODE_MAP = {
    javascript: "text/javascript",
    python: "text/x-python",
    java: "text/x-java",
    csharp: "text/x-csharp",
    sql: "text/x-sql",
    html: "text/html",
    css: "text/css",
    xml: "application/xml",
    json: "application/json",
    shell: "text/x-sh",
    powershell: "application/x-powershell",
    text: null,
    other: null
  };

  var editor = null;
  var cmInstances = [];

  function isLight() {
    return document.documentElement.getAttribute("data-theme") === "light";
  }

  function cmTheme() {
    return isLight() ? "default" : "material-darker";
  }

  function currentMode() {
    var kindSelect = document.getElementById("id_kind");
    if (kindSelect && kindSelect.value === "xml") {
      return MODE_MAP.xml;
    }
    var languageSelect = document.getElementById("id_language");
    if (languageSelect) {
      return MODE_MAP[languageSelect.value] || null;
    }
    return null;
  }

  function initEditor() {
    var area = document.getElementById("id_content");
    if (!area || typeof CodeMirror === "undefined") {
      return;
    }
    editor = CodeMirror.fromTextArea(area, {
      mode: currentMode(),
      theme: cmTheme(),
      lineNumbers: true,
      lineWrapping: false,
      indentUnit: 4,
      tabSize: 4,
      matchBrackets: true,
      autoCloseBrackets: true,
      styleActiveLine: true,
      viewportMargin: Infinity,
      extraKeys: {
        "Ctrl-/": "toggleComment",
        "Cmd-/": "toggleComment",
        "Tab": function (cm) {
          if (cm.somethingSelected()) {
            cm.indentSelection("add");
          } else {
            cm.replaceSelection("    ", "end");
          }
        }
      }
    });
    editor.on("change", function () { editor.save(); });
    cmInstances.push(editor);

    var languageSelect = document.getElementById("id_language");
    if (languageSelect) {
      languageSelect.addEventListener("change", function () {
        editor.setOption("mode", currentMode());
      });
    }
  }

  function initViewers() {
    var viewers = document.querySelectorAll("[data-code-viewer]");
    var i;
    if (typeof CodeMirror === "undefined") {
      // No JS highlighting available: fall back to a plain <pre>.
      for (i = 0; i < viewers.length; i++) {
        var src = viewers[i].querySelector("textarea");
        if (src) {
          var pre = document.createElement("pre");
          pre.className = "codeblock";
          pre.textContent = src.value;
          viewers[i].appendChild(pre);
        }
      }
      return;
    }
    for (i = 0; i < viewers.length; i++) {
      (function (holder) {
        var src = holder.querySelector("textarea");
        if (!src) { return; }
        var language = holder.getAttribute("data-language") || "text";
        var view = CodeMirror(function (el) { holder.appendChild(el); }, {
          value: src.value,
          mode: MODE_MAP[language] || null,
          theme: cmTheme(),
          lineNumbers: true,
          readOnly: true,
          viewportMargin: Infinity
        });
        cmInstances.push(view);

        // Give the holder a concrete height so the user can drag-resize it
        // (CSS resize: vertical). The editor fills whatever height it has.
        var contentHeight = view.getScrollInfo().height + 8;
        var maxInitial = Math.round(window.innerHeight * 0.62);
        holder.style.height = Math.max(140, Math.min(contentHeight, maxInitial)) + "px";
        view.setSize("100%", "100%");
        if (typeof ResizeObserver !== "undefined") {
          new ResizeObserver(function () { view.refresh(); }).observe(holder);
        }
      })(viewers[i]);
    }
  }

  /* ---- Light / dark theme toggle ------------------------------------- */

  function updateThemeButton() {
    var icon = document.getElementById("theme-icon");
    var label = document.getElementById("theme-label");
    if (icon) { icon.innerHTML = isLight() ? "&#9788;" : "&#9789;"; }
    if (label) { label.textContent = isLight() ? "Light mode" : "Dark mode"; }
  }

  function initThemeToggle() {
    var btn = document.getElementById("theme-toggle");
    if (!btn) { return; }
    updateThemeButton();
    btn.addEventListener("click", function () {
      var next = isLight() ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("cv-theme", next); } catch (err) { /* ignore */ }
      var i;
      for (i = 0; i < cmInstances.length; i++) {
        cmInstances[i].setOption("theme", cmTheme());
      }
      updateThemeButton();
    });
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
        label.textContent = "Paste not supported in this browser - use the file picker instead.";
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
      var kindSelect = document.getElementById("id_kind");
      if (kindSelect && kindSelect.value !== "image") {
        return; // let code paste go into the editor
      }
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

  /* ---- Item form: segmented type switch + conditional fields ----------- */

  function show(el, on) {
    if (el) { el.style.display = on ? "" : "none"; }
  }

  function applyKind(kind) {
    var zone = document.getElementById("dropzone");
    show(zone, kind === "image");
    show(document.getElementById("content-field"), kind !== "image");
    show(document.getElementById("language-row"), kind === "code");
    show(document.getElementById("script-type-field"), kind !== "image");
    show(document.getElementById("identifier-area"), kind !== "image");
    show(document.getElementById("related-field"), kind === "image");
    show(document.getElementById("upload-field"), kind !== "code");

    var buttons = document.querySelectorAll("#kind-switch button");
    var i;
    for (i = 0; i < buttons.length; i++) {
      buttons[i].className = buttons[i].getAttribute("data-kind") === kind ? "active" : "";
    }
    if (editor) {
      editor.setOption("mode", currentMode());
      editor.refresh();
    }
  }

  function initKindSwitch() {
    var wrap = document.getElementById("kind-switch");
    var kindSelect = document.getElementById("id_kind");
    if (!wrap || !kindSelect) {
      return;
    }
    var buttons = wrap.querySelectorAll("button");
    var i;
    for (i = 0; i < buttons.length; i++) {
      (function (btn) {
        btn.addEventListener("click", function () {
          kindSelect.value = btn.getAttribute("data-kind");
          applyKind(kindSelect.value);
        });
      })(buttons[i]);
    }
    if (!kindSelect.value) {
      kindSelect.value = wrap.getAttribute("data-initial") || "code";
    }
    applyKind(kindSelect.value);
  }

  function initIdentifierToggle() {
    var checkbox = document.getElementById("id_identifier_is_manual");
    var field = document.getElementById("identifier-field");
    if (!checkbox || !field) {
      return;
    }
    function apply() {
      show(field, checkbox.checked);
    }
    checkbox.addEventListener("change", apply);
    apply();
  }

  document.addEventListener("DOMContentLoaded", function () {
    initCopyButtons();
    initEditor();
    initViewers();
    initDropzone();
    initKindSwitch();
    initIdentifierToggle();
    initThemeToggle();
  });
})();
