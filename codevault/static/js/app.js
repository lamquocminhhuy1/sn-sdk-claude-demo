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
  var editorsByFieldId = {};

  var FORMATTERS = {
    "text/javascript": function (text) { return window.js_beautify(text); },
    "text/css": function (text) { return window.css_beautify(text); },
    "text/html": function (text) { return window.html_beautify(text); }
  };

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

  var PART_MODES = {
    main: null, // resolved via currentMode()
    html: "text/html",
    javascript: "text/javascript",
    css: "text/css"
  };

  function initEditors() {
    if (typeof CodeMirror === "undefined") {
      return;
    }
    var areas = document.querySelectorAll("textarea.code-area");
    var i;
    for (i = 0; i < areas.length; i++) {
      (function (area) {
        var partMode = area.getAttribute("data-mode") || "main";
        var cm = CodeMirror.fromTextArea(area, {
          mode: partMode === "main" ? currentMode() : PART_MODES[partMode],
          theme: cmTheme(),
          lineNumbers: true,
          lineWrapping: false,
          indentUnit: 4,
          tabSize: 4,
          matchBrackets: true,
          autoCloseBrackets: true,
          styleActiveLine: true,
          // viewportMargin: Infinity turns off CodeMirror's virtual
          // scrolling, forcing it to render every line as real DOM up
          // front. ServiceNow XML update-set exports routinely run tens of
          // thousands of lines, and content search (project_detail's q=
          // matches inside item content) makes those exact large items the
          // ones people click into most - rendering one this way is a
          // multi-second main-thread block that reads as the browser
          // hanging. A generous but finite margin still makes scrolling
          // feel seamless without paying for the whole document at once.
          viewportMargin: 100,
          extraKeys: {
            "Ctrl-/": "toggleComment",
            "Cmd-/": "toggleComment",
            "Tab": function (inner) {
              if (inner.somethingSelected()) {
                inner.indentSelection("add");
              } else {
                inner.replaceSelection("    ", "end");
              }
            }
          }
        });
        cm.on("change", function () { cm.save(); });
        cmInstances.push(cm);
        editorsByFieldId[area.id] = cm;
        if (partMode === "main") {
          editor = cm;
        }
      })(areas[i]);
    }

    var languageSelect = document.getElementById("id_language");
    if (languageSelect && editor) {
      languageSelect.addEventListener("change", function () {
        editor.setOption("mode", currentMode());
        updateFormatButtonState(editor);
      });
    }

    initEditorToolbars();
  }

  /* ---- Editor toolbar: comment / format / find ------------------------ */

  function updateFormatButtonState(cm) {
    var btn = document.querySelector('.editor-toolbar[data-editor-for="' + cm.getTextArea().id + '"] [data-action="format"]');
    if (!btn) { return; }
    var supported = typeof FORMATTERS[cm.getOption("mode")] === "function" && typeof window.js_beautify === "function";
    btn.disabled = !supported;
    btn.title = supported ? "Format code" : "Formatting isn't supported for this language";
  }

  function initEditorToolbars() {
    var toolbars = document.querySelectorAll(".editor-toolbar[data-editor-for]");
    var i;
    for (i = 0; i < toolbars.length; i++) {
      (function (bar) {
        var fieldId = bar.getAttribute("data-editor-for");
        var commentBtn = bar.querySelector('[data-action="comment"]');
        var formatBtn = bar.querySelector('[data-action="format"]');
        var findBtn = bar.querySelector('[data-action="find"]');

        function cm() { return editorsByFieldId[fieldId]; }

        if (commentBtn) {
          commentBtn.addEventListener("click", function () {
            var inst = cm();
            if (inst) { inst.execCommand("toggleComment"); inst.focus(); }
          });
        }
        if (findBtn) {
          findBtn.addEventListener("click", function () {
            var inst = cm();
            if (inst) { inst.execCommand("find"); }
          });
        }
        if (formatBtn) {
          formatBtn.addEventListener("click", function () {
            var inst = cm();
            if (!inst || formatBtn.disabled) { return; }
            var formatter = FORMATTERS[inst.getOption("mode")];
            if (!formatter) { return; }
            try {
              var cursor = inst.getCursor();
              inst.setValue(formatter(inst.getValue()));
              inst.setCursor(cursor);
              inst.focus();
            } catch (err) {
              // Malformed source the beautifier can't parse: leave it untouched
              // rather than risk mangling the user's code.
            }
          });
          var inst = cm();
          if (inst) { updateFormatButtonState(inst); }
        }
      })(toolbars[i]);
    }
  }

  function refreshEditors() {
    var i;
    for (i = 0; i < cmInstances.length; i++) {
      cmInstances[i].refresh();
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
          // See the matching comment in initEditors() above: this holder is
          // already capped to 62vh and scrolls internally (.cm-viewer{
          // overflow:auto} in the CSS), so Infinity bought nothing but the
          // cost of rendering the whole file - the exact freeze a big XML
          // export triggers.
          viewportMargin: 100
        });
        cmInstances.push(view);

        // Give the holder a concrete height so the user can drag-resize it
        // (CSS resize: vertical). The editor fills whatever height it has.
        // getScrollInfo().height reflects CodeMirror's estimated total
        // document height, which it tracks even without full rendering.
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
    if (icon) { icon.innerHTML = isLight() ? "&#9728;" : "&#9790;"; }
    if (label) { label.textContent = isLight() ? "Light Mode" : "Dark Mode"; }
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

  /* ---- Sidebar collapse ------------------------------------------------ */

  function initSidebarToggle() {
    var btn = document.getElementById("sidebar-toggle");
    if (!btn) { return; }
    btn.addEventListener("click", function () {
      var collapsed = document.documentElement.getAttribute("data-sidebar") === "collapsed";
      var next = collapsed ? "" : "collapsed";
      if (next) {
        document.documentElement.setAttribute("data-sidebar", next);
      } else {
        document.documentElement.removeAttribute("data-sidebar");
      }
      try { localStorage.setItem("cv-sidebar-collapsed", next ? "1" : "0"); } catch (err) { /* ignore */ }
      btn.setAttribute("aria-expanded", next ? "false" : "true");
      refreshEditors();
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
      if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) {
        return;
      }
      var file = e.dataTransfer.files[0];
      if (file.type.indexOf("image/") === 0) {
        acceptImage(zone, input, file);
      } else if (setFileInput(input, file)) {
        // Non-image file (e.g. .xml): hand it to the file input directly.
        zone.className = "dropzone armed";
        var label = zone.querySelector(".dz-label");
        if (label) { label.textContent = "File ready: " + file.name; }
      }
    });

    input.addEventListener("change", function () {
      if (input.files && input.files.length) {
        showPreview(zone, input.files[0]);
      }
    });
  }

  /* ---- Item form: segmented type switch + per-component fields --------- */

  function show(el, on) {
    if (el) { el.style.display = on ? "" : "none"; }
  }

  // Which metadata fields, extra code parts, and labels each ServiceNow
  // component type gets. Mirrors the real platform schemas.
  var SN_SCHEMA = {
    script_include: { fields: ["callable-field"], contentLabel: "Script" },
    business_rule: {
      fields: ["subtype-field", "table-field", "order-field", "operations-field", "condition-field"],
      subtypeLabel: "When", subtypes: ["before", "after", "async", "display"],
      contentLabel: "Script"
    },
    client_script: {
      fields: ["subtype-field", "table-field", "fieldname-field"],
      subtypeLabel: "Type", subtypes: ["onload", "onchange", "onsubmit", "oncelledit"],
      contentLabel: "Script"
    },
    ui_page: {
      parts: ["html-part", "client-part"],
      contentLabel: "Processing Script"
    },
    ui_action: { fields: ["table-field", "condition-field"], contentLabel: "Script" },
    ui_macro: { contentLabel: "XML (Jelly)" },
    scheduled_job: { contentLabel: "Script" },
    fix_script: { contentLabel: "Script" },
    rest_api: { fields: ["endpoint-field"], contentLabel: "Operation Script" },
    widget: {
      parts: ["html-part", "client-part", "css-part"],
      partLabels: { "html-part": "HTML Template", "client-part": "Client Controller" },
      contentLabel: "Server Script"
    },
    xml: { contentLabel: "XML Content" },
    other: { contentLabel: "Source Code" }
  };
  var DEFAULT_PART_LABELS = { "html-part": "HTML (Jelly)", "client-part": "Client Script" };
  var subtypeOptions = null; // captured from the full select on first use

  function applyScriptType() {
    var kindSelect = document.getElementById("id_kind");
    var typeSelect = document.getElementById("id_script_type");
    if (!typeSelect) { return; }
    var kind = kindSelect ? kindSelect.value : "code";
    var schema = SN_SCHEMA[typeSelect.value] || SN_SCHEMA.other;
    var isCode = kind === "code";
    var i;

    var snFields = document.querySelectorAll(".sn-field");
    for (i = 0; i < snFields.length; i++) {
      var visible = isCode && (schema.fields || []).indexOf(snFields[i].id) !== -1;
      snFields[i].style.display = visible ? "" : "none";
    }
    var parts = document.querySelectorAll(".code-part");
    for (i = 0; i < parts.length; i++) {
      var partOn = isCode && (schema.parts || []).indexOf(parts[i].id) !== -1;
      parts[i].style.display = partOn ? "" : "none";
      var labelEl = parts[i].querySelector("[data-part-label]");
      if (labelEl) {
        labelEl.textContent =
          (schema.partLabels && schema.partLabels[parts[i].id]) ||
          DEFAULT_PART_LABELS[parts[i].id] || labelEl.textContent;
      }
    }

    var contentLabel = document.getElementById("content-label");
    if (contentLabel) {
      contentLabel.textContent = kind === "xml" ? "XML Content" : schema.contentLabel;
    }
    var subtypeLabel = document.getElementById("subtype-label");
    if (subtypeLabel && schema.subtypeLabel) {
      subtypeLabel.textContent = schema.subtypeLabel;
    }

    // Narrow the sub_type select to the options valid for this component.
    var subSelect = document.getElementById("id_sub_type");
    if (subSelect) {
      if (!subtypeOptions) {
        subtypeOptions = [];
        for (i = 0; i < subSelect.options.length; i++) {
          subtypeOptions.push({
            value: subSelect.options[i].value,
            text: subSelect.options[i].text
          });
        }
      }
      var wanted = schema.subtypes || [];
      var current = subSelect.value;
      subSelect.innerHTML = "";
      for (i = 0; i < subtypeOptions.length; i++) {
        var opt = subtypeOptions[i];
        if (opt.value === "" || wanted.indexOf(opt.value) !== -1) {
          var el = document.createElement("option");
          el.value = opt.value;
          el.text = opt.text;
          subSelect.appendChild(el);
        }
      }
      subSelect.value = wanted.indexOf(current) !== -1 ? current : "";
    }
    refreshEditors();
  }

  function applyKind(kind) {
    var zone = document.getElementById("dropzone");
    show(zone, kind !== "code");
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
      updateFormatButtonState(editor);
    }
    applyScriptType();
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
    var typeSelect = document.getElementById("id_script_type");
    if (typeSelect) {
      typeSelect.addEventListener("change", applyScriptType);
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

  function initProjectScopeToggle() {
    var select = document.getElementById("id_scope_type");
    var field = document.getElementById("scope-name-field");
    if (!select || !field) {
      return;
    }
    function apply() {
      show(field, select.value === "scoped_app");
    }
    select.addEventListener("change", apply);
    apply();
  }

  /* ---- Dependency-tree collapse/expand --------------------------------- */

  function setNodeCollapsed(li, collapsed) {
    li.classList.toggle("collapsed", collapsed);
    var toggle = li.querySelector(".tree-card > .tree-toggle");
    if (toggle) {
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    }
  }

  function expandAncestors(li) {
    var container = li.parentElement; // the <ul class="tree"> holding this node
    while (container) {
      var ancestor = container.closest(".tree-node");
      if (!ancestor) {
        break;
      }
      setNodeCollapsed(ancestor, false);
      container = ancestor.parentElement;
    }
  }

  function initDepsTree() {
    var expandAllBtn = document.getElementById("tree-expand-all");
    var collapseAllBtn = document.getElementById("tree-collapse-all");
    if (!expandAllBtn && !collapseAllBtn && !document.querySelector(".tree-toggle")) {
      return;
    }

    document.addEventListener("click", function (e) {
      var btn = e.target.closest(".tree-toggle");
      if (!btn) {
        return;
      }
      var li = btn.closest(".tree-node");
      if (!li) {
        return;
      }
      setNodeCollapsed(li, !li.classList.contains("collapsed"));
    });

    if (expandAllBtn) {
      expandAllBtn.addEventListener("click", function () {
        var i, nodes = document.querySelectorAll(".tree-node.has-children");
        for (i = 0; i < nodes.length; i++) { setNodeCollapsed(nodes[i], false); }
      });
    }
    if (collapseAllBtn) {
      collapseAllBtn.addEventListener("click", function () {
        var i, nodes = document.querySelectorAll(".tree-node.has-children");
        for (i = 0; i < nodes.length; i++) { setNodeCollapsed(nodes[i], true); }
      });
    }
  }

  /* ---- Dependency-tree filter ----------------------------------------- */

  function initDepsFilter() {
    var input = document.getElementById("deps-filter");
    if (!input) { return; }
    input.addEventListener("input", function () {
      var q = input.value.toLowerCase();
      var nodes = document.querySelectorAll(".tree-node");
      var cards = document.querySelectorAll(".sa-card");
      var i, matches;
      // A tree node stays visible when its subtree mentions the query,
      // so ancestors of a match never disappear. Matching nodes also force
      // any collapsed ancestor open so the result is actually visible.
      for (i = 0; i < nodes.length; i++) {
        matches = !q || nodes[i].textContent.toLowerCase().indexOf(q) !== -1;
        nodes[i].style.display = matches ? "" : "none";
        if (matches && q) {
          expandAncestors(nodes[i]);
        }
      }
      for (i = 0; i < cards.length; i++) {
        cards[i].style.display =
          !q || cards[i].textContent.toLowerCase().indexOf(q) !== -1 ? "" : "none";
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initCopyButtons();
    initEditors();
    initViewers();
    initDropzone();
    initKindSwitch();
    initIdentifierToggle();
    initProjectScopeToggle();
    initThemeToggle();
    initSidebarToggle();
    initDepsTree();
    initDepsFilter();
  });
})();
