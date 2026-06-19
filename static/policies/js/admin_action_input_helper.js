// admin_action_input_helper.js
(function () {
  "use strict";

  function replaceDummyUrl(baseUrl, realId) {
    var dummy = "00000000-0000-0000-0000-000000000000";
    return baseUrl.replace(dummy, realId);
  }

  function normalizeValue(val) {
    if (val === undefined || val === null || val === "") return null;
    return String(val);
  }

  function parseJsonSafe(raw, fallback) {
    try { return JSON.parse(raw); } catch (e) { return fallback; }
  }

  function clearNode(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function findActionTypeElement() {
    return document.getElementById("id_action_type") || document.querySelector("[name='action_type']");
  }

  function getInputField() {
    return document.getElementById("id_input") || document.querySelector("input[name='input'], textarea[name='input']");
  }

  function getRow(el) {
    if (!el || !el.closest) return null;
    return el.closest(".form-row, .fieldBox, .field-box, .field-dynamic_input_fields_display, .field-input");
  }

  function hide(el) { if (el) el.style.display = "none"; }
  function show(el) { if (el) el.style.display = ""; }

  function createFieldWrapper(labelText, required) {
    var wrapper = document.createElement("div");
    wrapper.className = "admin-schema-field form-group";

    var label = document.createElement("label");
    if (required) label.className = "required";
    label.textContent = labelText;
    wrapper.appendChild(label);

    return wrapper;
  }


  function prettifyLabel(name) {
    if (!name) return "";
    return String(name)
      .replace(/[_-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  function createBooleanSwitch(name, value) {
    var switchWrap = document.createElement("label");
    switchWrap.className = "admin-schema-checkbox-wrap";

    var checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = value === true;
    checkbox.setAttribute("data-schema-field", name);
    checkbox.className = "admin-schema-checkbox";

    var stateText = document.createElement("span");
    stateText.className = "admin-schema-checkbox-state";
    stateText.textContent = "Enabled";

    switchWrap.appendChild(checkbox);
    switchWrap.appendChild(stateText);

    return { input: checkbox, wrapper: switchWrap };
  }

  function enhanceSelectWithSelect2(selectEl) {
    if (!window.jQuery || !window.jQuery.fn || !window.jQuery.fn.select2) return;

    var $select = window.jQuery(selectEl);
    if ($select.data("select2")) {
      $select.select2("destroy");
    }

    $select.select2({
      width: "100%",
      dropdownAutoWidth: true,
      minimumResultsForSearch: 6
    });
  }

  function createControl(name, schema, value) {
    var type = schema && schema.type ? schema.type : "string";
    var input;

    if (type === "boolean") {
      return createBooleanSwitch(name, value);
    }

    if (Array.isArray(schema.enum) && schema.enum.length) {
      input = document.createElement("select");
      input.className = "admin-schema-select form-control";

      schema.enum.forEach(function (v) {
        var option = document.createElement("option");
        option.value = String(v);
        option.textContent = String(v);
        input.appendChild(option);
      });

      if (value !== undefined && value !== null && schema.enum.indexOf(value) !== -1) {
        input.value = String(value);
      } else if (schema.enum.length) {
        input.value = String(schema.enum[0]);
      }

      setTimeout(function () { enhanceSelectWithSelect2(input); }, 0);

      return { input: input };
    }

    if (type === "integer" || type === "number") {
      input = document.createElement("input");
      input.type = "number";
      input.className = "admin-schema-input form-control";
      input.step = type === "integer" ? "1" : "any";
      if (schema.minimum !== undefined) input.min = String(schema.minimum);
      if (schema.maximum !== undefined) input.max = String(schema.maximum);
      input.value = value !== undefined && value !== null ? String(value) : "";
      return { input: input };
    }

    input = document.createElement("input");
    input.type = "text";
    input.className = "admin-schema-input form-control";
    input.value = value !== undefined && value !== null ? String(value) : "";

    return { input: input };
  }

  function getValueFromControl(input, schema) {
    var type = schema && schema.type ? schema.type : "string";
    if (type === "boolean") return !!input.checked;
    if (type === "integer") {
      if (input.value === "") return null;
      var n = parseInt(input.value, 10);
      return isNaN(n) ? null : n;
    }
    if (type === "number") {
      if (input.value === "") return null;
      var f = parseFloat(input.value);
      return isNaN(f) ? null : f;
    }
    return input.value;
  }

  function fetchSchema(baseUrl, actionTypeId) {
    if (!actionTypeId) return Promise.resolve({ schema: null });

    var url = replaceDummyUrl(baseUrl, actionTypeId);
    return fetch(url, {
      method: "GET",
      credentials: "same-origin",
      headers: { "Accept": "application/json" }
    })
      .then(function (resp) { return resp.ok ? resp.json() : { schema: null }; })
      .catch(function () { return { schema: null }; });
  }

  function init() {
    var container = document.getElementById("action-type-schema-fields");
    if (!container) return false;

    var inputField = getInputField();
    var actionTypeEl = findActionTypeElement();
    if (!inputField || !actionTypeEl) return false;

    var baseUrl = container.getAttribute("data-base-url");
    if (!baseUrl) return false;

    var containerRow = getRow(container);
    hide(containerRow);

    var initialInput = parseJsonSafe(container.getAttribute("data-initial-input") || "{}", {});
    var activeSchema = null;
    var requestToken = 0;

    function collectPayload() {
      if (!activeSchema || activeSchema.type !== "object" || !activeSchema.properties) return {};
      var payload = {};
      Object.keys(activeSchema.properties).forEach(function (name) {
        var schema = activeSchema.properties[name] || {};
        var field = container.querySelector("[data-schema-field='" + name + "']");
        if (!field) return;
        var value = getValueFromControl(field, schema);
        if (value === "" || value === null || value === undefined) return;
        payload[name] = value;
      });
      return payload;
    }

    function syncInputJson() {
      inputField.value = JSON.stringify(collectPayload());
    }

    function buildFields(values) {
      clearNode(container);

      if (!activeSchema || activeSchema.type !== "object" || !activeSchema.properties) {
        hide(containerRow);
        inputField.value = "{}";
        return;
      }

      var required = Array.isArray(activeSchema.required) ? activeSchema.required : [];

      Object.keys(activeSchema.properties).forEach(function (name) {
        var schema = activeSchema.properties[name] || {};
        var wrapper = createFieldWrapper(prettifyLabel(name), required.indexOf(name) !== -1);

        if (schema.description) {
          var desc = document.createElement("div");
          desc.textContent = schema.description;
          desc.style.fontSize = "12px";
          desc.style.color = "#666";
          desc.style.marginBottom = "3px";
          wrapper.appendChild(desc);
        }

        var control = createControl(name, schema, values ? values[name] : undefined);
        if (!control.input.hasAttribute("data-schema-field")) {
          control.input.setAttribute("data-schema-field", name);
        }
        if (required.indexOf(name) !== -1) control.input.required = true;
        control.input.addEventListener("input", syncInputJson);
        control.input.addEventListener("change", syncInputJson);

        if (control.wrapper) {
          wrapper.appendChild(control.wrapper);
        } else {
          wrapper.appendChild(control.input);
        }

        container.appendChild(wrapper);
      });

      show(containerRow);
      syncInputJson();
    }

    function getSelectedActionTypeId() {
      return normalizeValue(actionTypeEl.value);
    }

    function onActionTypeChanged(resetValues) {
      var selectedId = getSelectedActionTypeId();
      if (!selectedId) {
        activeSchema = null;
        clearNode(container);
        hide(containerRow);
        inputField.value = "{}";
        return;
      }

      requestToken += 1;
      var myToken = requestToken;
      fetchSchema(baseUrl, selectedId).then(function (data) {
        if (myToken !== requestToken) return;
        activeSchema = data ? data.schema : null;
        var currentValues = resetValues ? {} : parseJsonSafe(inputField.value || "{}", initialInput);
        buildFields(currentValues);
      });
    }

    actionTypeEl.addEventListener("change", function () { onActionTypeChanged(true); });

    if (window.jQuery) {
      try {
        window.jQuery(document).on("select2:select", "#id_action_type", function () {
          onActionTypeChanged(true);
        });
      } catch (e) { /* ignore */ }
    }

    var form = inputField.closest("form");
    if (form) form.addEventListener("submit", syncInputJson);

    onActionTypeChanged(false);
    return true;
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (init()) return;

    var start = Date.now();
    var observer = new MutationObserver(function (_m, obs) {
      if (init()) {
        obs.disconnect();
        return;
      }
      if (Date.now() - start > 8000) obs.disconnect();
    });

    observer.observe(document.documentElement || document.body, { childList: true, subtree: true });
  });
})();