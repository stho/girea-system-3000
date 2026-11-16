/*
 * Gira System 3000 week profile card
 * Same look & feel as "cul-max-week-profile-card" (MAX! integration).
 * Entities derived from the climate entity <base>:
 *   text.<base>_1_montag ... _7_sonntag, switch.<base>_wochenplan_aktiv,
 *   button.<base>_wochenplan_ubertragen / _entwurf_verwerfen / _vom_gerat_lesen
 * Edits are a draft until transferred (like the integration's own concept).
 */
const GDAYS = [
  ["monday", "Mo", "Montag", "1_montag"],
  ["tuesday", "Di", "Dienstag", "2_dienstag"],
  ["wednesday", "Mi", "Mittwoch", "3_mittwoch"],
  ["thursday", "Do", "Donnerstag", "4_donnerstag"],
  ["friday", "Fr", "Freitag", "5_freitag"],
  ["saturday", "Sa", "Samstag", "6_samstag"],
  ["sunday", "So", "Sonntag", "7_sonntag"],
];
const G_JS_DAY_TO_KEY = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
const G_TEMP_MIN = 5;
const G_TEMP_MAX = 30;
const G_DEFAULT_MAX_POINTS = 40;
const G_LOCALE = "de-DE";

const gEsc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);

const gToMinutes = (hhmm) => {
  const match = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm || "").trim());
  if (!match) return NaN;
  return Number(match[1]) * 60 + Number(match[2]);
};
const gToHHMM = (minutes) => {
  if (!Number.isFinite(minutes)) return "--:--";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
};
const gFmtTemp = (temp) => {
  const value = Number(temp);
  if (!Number.isFinite(value)) return "–";
  return `${value.toLocaleString(G_LOCALE, { minimumFractionDigits: 0, maximumFractionDigits: 1 })} °C`;
};

const G_TEMP_BANDS = [
  [G_TEMP_MIN, "#8a8f98"],
  [12, "#3d6fb6"],
  [17, "#3f8fc4"],
  [19.5, "#2f9e9e"],
  [21, "#d08a1e"],
  [23, "#e0692a"],
  [99, "#cf4a3c"],
];
const gTempColor = (temp) => {
  const value = Number(temp);
  if (!Number.isFinite(value)) return G_TEMP_BANDS[0][1];
  return G_TEMP_BANDS.find(([limit]) => value <= limit)[1];
};

/** "5,06:00,21,18:00,5" -> [{from, until, temp}] in minutes. */
const gParseDay = (raw) => {
  if (!raw || typeof raw !== "string") return [];
  const tokens = raw.split(",").map((t) => t.trim()).filter(Boolean);
  if (!tokens.length) return [];
  const segments = [];
  let from = 0;
  let temp = Number(tokens[0]);
  for (let i = 1; i < tokens.length; i += 2) {
    let until = gToMinutes(tokens[i]);
    if (!Number.isFinite(until)) break;
    if (until === 0) until = 24 * 60;
    if (until > from) segments.push({ from, until, temp });
    from = until;
    if (until >= 24 * 60) break;
    if (tokens[i + 1] !== undefined) temp = Number(tokens[i + 1]);
  }
  if (from < 24 * 60) segments.push({ from, until: 24 * 60, temp });
  return segments.reduce((acc, seg) => {
    const last = acc[acc.length - 1];
    if (last && last.temp === seg.temp && last.until === seg.from) last.until = seg.until;
    else acc.push({ ...seg });
    return acc;
  }, []);
};
const gFmtNum = (temp) => (Number.isInteger(temp) ? String(temp) : Number(temp).toFixed(1));
const gSerializeDay = (segments) => {
  const parts = [];
  segments.forEach((seg, idx) => {
    parts.push(gFmtNum(seg.temp));
    if (idx < segments.length - 1) parts.push(gToHHMM(seg.until));
  });
  return parts.join(",");
};
const gValidateDay = (segments) => {
  if (!segments.length) return "Mindestens ein Abschnitt ist nötig.";
  let previous = 0;
  for (let i = 0; i < segments.length; i += 1) {
    const seg = segments[i];
    if (!(seg.temp >= G_TEMP_MIN && seg.temp <= G_TEMP_MAX) || (seg.temp * 2) % 1 !== 0) {
      return `Ungültige Temperatur: ${seg.temp}`;
    }
    if (i < segments.length - 1) {
      if (!Number.isFinite(seg.until)) return "Bitte alle Zeiten als hh:mm eintragen.";
      if (seg.until <= previous) return `Die Zeit ${gToHHMM(seg.until)} muss nach der vorherigen liegen.`;
      if (seg.until >= 24 * 60) return "Die letzte Schaltzeit muss vor 24:00 liegen.";
      previous = seg.until;
    }
  }
  return null;
};

class GiraWeekProfileCard extends HTMLElement {
  static getStubConfig(hass) {
    const entity =
      Object.keys(hass?.states || {}).find(
        (id) => id.startsWith("climate.") && hass.states[`switch.${id.slice(8)}_wochenplan_aktiv`]
      ) || "";
    return { entity, show_current_temp: true, editable: true };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._editing = null;
    this._transfer = null;
  }

  setConfig(config) {
    if (!config || !config.entity) throw new Error("Entity required");
    this._config = { show_current_temp: true, editable: true, ...config };
    this._lastStates = null;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const states = this._allIds().map((id) => hass?.states?.[id]);
    const changed = !this._lastStates || states.some((st, idx) => st !== this._lastStates[idx]);
    if (changed) {
      this._lastStates = states;
      this._render();
    }
  }

  connectedCallback() {
    this._timer = window.setInterval(() => this._render(), 60 * 1000);
  }
  disconnectedCallback() {
    window.clearInterval(this._timer);
  }
  getCardSize() {
    return 6;
  }
  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  _ids() {
    const cfg = this._config;
    const base = String(cfg.entity).split(".")[1];
    const days = Array.isArray(cfg.days) && cfg.days.length === 7
      ? cfg.days
      : GDAYS.map(([, , , suffix]) => `text.${base}_${suffix}`);
    return {
      climate: cfg.entity,
      days,
      active: cfg.active || `switch.${base}_wochenplan_aktiv`,
      apply: cfg.apply || `button.${base}_wochenplan_ubertragen`,
      discard: cfg.discard || `button.${base}_wochenplan_entwurf_verwerfen`,
      read: cfg.read || `button.${base}_wochenplan_vom_gerat_lesen`,
    };
  }
  _allIds() {
    if (!this._config) return [];
    const ids = this._ids();
    return [ids.climate, ...ids.days, ids.active];
  }
  _st(id) {
    return this._hass?.states?.[id];
  }
  _dayText(idx) {
    return this._st(this._ids().days[idx])?.state;
  }
  _daySegments(idx) {
    return gParseDay(this._dayText(idx));
  }
  _dayHasDraft(idx) {
    const st = this._st(this._ids().days[idx]);
    const dev = st?.attributes?.device_value;
    return Boolean(st && dev != null && dev !== st.state);
  }
  _hasDraft() {
    return GDAYS.some((_, idx) => this._dayHasDraft(idx)) ||
      this._ids().days.some((id) => this._st(id)?.attributes?.draft_pending);
  }

  _nextSwitch(now) {
    const nowMin = now.getHours() * 60 + now.getMinutes();
    const todayIdx = (now.getDay() + 6) % 7;
    let current = null;
    for (let off = 0; off <= 7; off += 1) {
      const idx = (todayIdx + off) % 7;
      for (const seg of this._daySegments(idx)) {
        if (off === 0 && seg.until <= nowMin) continue;
        if (off === 0 && seg.from <= nowMin) { current = seg.temp; continue; }
        if (current === null) { current = seg.temp; continue; }
        if (seg.temp !== current) return { off, idx, minute: seg.from, temp: seg.temp };
      }
    }
    return null;
  }

  _render() {
    if (!this._hass || !this._config) return;
    const root = this.shadowRoot;
    const ids = this._ids();
    const climate = this._st(ids.climate);
    const missing = [ids.climate, ...ids.days].filter((id) => !this._st(id));
    if (!climate || missing.length) {
      root.innerHTML = `<ha-card><div class="msg">Entität nicht gefunden: ${gEsc(missing.join(", "))}</div></ha-card>${this._styles()}`;
      return;
    }
    const attrs = climate.attributes || {};
    const activeSt = this._st(ids.active);
    const isActive = activeSt ? activeSt.state === "on" : null;
    const editable = this._config.editable !== false;
    const now = new Date();
    const nowMinutes = now.getHours() * 60 + now.getMinutes();
    const todayKey = G_JS_DAY_TO_KEY[now.getDay()];
    const draft = this._hasDraft();
    const firstDay = this._st(ids.days[0])?.attributes || {};
    const used = firstDay.switch_points_used;
    const maxPoints = firstDay.switch_points_max ?? G_DEFAULT_MAX_POINTS;

    const chips = [];
    if (isActive !== null) chips.push(`<span class="chip mode">${isActive ? "Wochenplan aktiv" : "Wochenplan aus"}</span>`);
    if (attrs.temperature != null) chips.push(`<span class="chip"><ha-icon icon="mdi:target"></ha-icon>${gFmtTemp(attrs.temperature)}</span>`);
    if (this._config.show_current_temp && attrs.current_temperature != null) {
      chips.push(`<span class="chip"><ha-icon icon="mdi:thermometer"></ha-icon>${gFmtTemp(attrs.current_temperature)}</span>`);
    }
    if (used != null) chips.push(`<span class="chip"><ha-icon icon="mdi:calendar-clock"></ha-icon>${used}/${maxPoints}</span>`);

    const next = this._nextSwitch(now);
    let nextHtml = "";
    if (next) {
      const when = next.off === 0 ? gToHHMM(next.minute) : `${GDAYS[next.idx][2]} ${gToHHMM(next.minute)}`;
      nextHtml = `<div class="next"><ha-icon icon="mdi:clock-outline"></ha-icon>Nächste Schaltung: ${when} Uhr → ${gFmtTemp(next.temp)}</div>`;
    }

    const statusItems = [];
    if (isActive === false) statusItems.push({ level: "info", icon: "mdi:calendar-remove", text: "Der Wochenplan ist ausgeschaltet – das Thermostat hält den Sollwert." });
    if (this._transfer?.error) statusItems.push({ level: "error", icon: "mdi:alert-circle-outline", text: gEsc(this._transfer.error) });
    const status = statusItems
      .map((item) => `<div class="status ${item.level}"><ha-icon icon="${item.icon}"></ha-icon><span>${item.text}</span></div>`)
      .join("");

    const draftHtml = draft
      ? `<div class="status warn"><ha-icon icon="mdi:pencil-outline"></ha-icon><span>Entwurf – noch nicht auf das Thermostat übertragen.</span></div>
         <div class="draft-actions">
           <button class="text draft-discard" ${this._transfer?.busy ? "disabled" : ""}>Verwerfen</button>
           <button class="primary draft-apply" ${this._transfer?.busy ? "disabled" : ""}>${this._transfer?.busy ? "Übertrage…" : "Übertragen"}</button>
         </div>`
      : "";

    const rows = GDAYS.map(([key, short, long], idx) => {
      const isToday = key === todayKey;
      const segments = this._daySegments(idx);
      const bar = segments.length
        ? segments.map((seg) => {
            const left = (seg.from / 1440) * 100;
            const width = ((seg.until - seg.from) / 1440) * 100;
            const active = isToday && nowMinutes >= seg.from && nowMinutes < seg.until;
            return `<div class="seg${active ? " active" : ""}" style="left:${left}%;width:${width}%;background:${gTempColor(seg.temp)}"
                  title="${long} ${gToHHMM(seg.from)}–${gToHHMM(seg.until)}: ${gFmtTemp(seg.temp)}">${width >= 9 ? `<span>${gFmtTemp(seg.temp)}</span>` : ""}</div>`;
          }).join("")
        : `<div class="empty">unbekannt</div>`;
      const marker = isToday ? `<div class="now" style="left:${(nowMinutes / 1440) * 100}%"></div>` : "";
      const lastOnLine = [-Infinity, -Infinity];
      let lines = 1;
      const times = segments.slice(1).map((seg) => {
        const pos = (seg.from / 1440) * 100;
        const line = pos - lastOnLine[0] >= 8 ? 0 : pos - lastOnLine[1] >= 8 ? 1 : 0;
        lastOnLine[line] = pos;
        lines = Math.max(lines, line + 1);
        return `<span class="l${line}" style="left:${pos}%">${gToHHMM(seg.from)}</span>`;
      }).join("");
      const editingThis = this._editing?.day === key;
      const dayDraft = this._dayHasDraft(idx);
      return `
        <div class="day-row${isToday ? " today" : ""}${editable ? " editable" : ""}${editingThis ? " editing" : ""}" data-day="${key}" ${editable ? `role="button" tabindex="0" aria-label="${gEsc(long)} bearbeiten"` : ""}>
          <div class="label">${short}${dayDraft ? `<span class="diff" title="Entwurf">✎</span>` : ""}</div>
          <div class="track"><div class="bar">${bar}${marker}</div><div class="times${lines > 1 ? " two" : ""}">${times}</div></div>
        </div>
        ${editingThis ? this._editorHtml(key, long) : ""}`;
    }).join("");

    root.innerHTML = `
      <ha-card>
        <div class="wrapper">
          <div class="header">
            <div class="titles">
              <div class="title">${gEsc(this._config.title || "Wochenprofil")}</div>
              <div class="subtitle">${gEsc(attrs.friendly_name || "")}</div>
            </div>
            <div class="more-wrap">
              <ha-icon-button class="more" label="Details"><ha-icon icon="mdi:dots-vertical"></ha-icon></ha-icon-button>
              <div class="more-menu" hidden>
                <button class="more-item" data-act="details">Thermostat-Details</button>
                <button class="more-item" data-act="read">Wochenplan vom Gerät lesen</button>
                ${activeSt ? `<button class="more-item" data-act="toggle">Wochenplan ${isActive ? "ausschalten" : "einschalten"}</button>` : ""}
              </div>
            </div>
          </div>
          <div class="chips">${chips.join("")}</div>
          ${nextHtml}${status}${draftHtml}
          <div class="axis"><span>0</span><span>6</span><span>12</span><span>18</span><span>24</span></div>
          <div class="days">${rows}</div>
          ${editable && !this._editing ? `<div class="hint">Tag antippen zum Bearbeiten</div>` : ""}
        </div>
      </ha-card>${this._styles()}`;
    this._bindEvents(editable);
  }

  _editorHtml(dayKey, longLabel) {
    const ed = this._editing;
    const tempOptions = (selected) => {
      const options = [];
      for (let t = G_TEMP_MIN; t <= G_TEMP_MAX + 0.001; t += 0.5) {
        options.push(`<option value="${t}" ${Math.abs(t - selected) < 0.01 ? "selected" : ""}>${t.toLocaleString(G_LOCALE, { minimumFractionDigits: 1 })}</option>`);
      }
      return options.join("");
    };
    const segRows = ed.segments.map((seg, idx) => {
      const last = idx === ed.segments.length - 1;
      return `
        <div class="ed-seg" data-idx="${idx}">
          <span class="ed-from">${gToHHMM(seg.from)}</span><span class="ed-dash">–</span>
          ${last ? `<span class="ed-until fixed">24:00</span>`
                 : `<input class="ed-until" type="text" inputmode="numeric" maxlength="5" placeholder="hh:mm" aria-label="bis" value="${Number.isFinite(seg.until) ? gToHHMM(seg.until) : ""}" ${ed.busy ? "disabled" : ""}>`}
          <select class="ed-temp" ${ed.busy ? "disabled" : ""}>${tempOptions(seg.temp)}</select><span class="ed-unit">°C</span>
          <button class="icon ed-remove" title="Abschnitt entfernen" ${ed.segments.length <= 1 || ed.busy ? "disabled" : ""}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>`;
    }).join("");
    const copyBoxes = GDAYS.filter(([key]) => key !== dayKey)
      .map(([key, short]) => `<label class="copy"><input type="checkbox" data-copy="${key}" ${ed.copyTo.has(key) ? "checked" : ""} ${ed.busy ? "disabled" : ""}>${short}</label>`)
      .join("");
    return `
      <div class="editor">
        <div class="ed-title">${gEsc(longLabel)} bearbeiten</div>
        <div class="ed-list">${segRows}</div>
        <button class="text ed-add" ${ed.busy ? "disabled" : ""}><ha-icon icon="mdi:plus"></ha-icon>Schaltzeit hinzufügen</button>
        <div class="ed-copy">
          <span>Auch übernehmen für:</span>
          <div class="copy-days">${copyBoxes}</div>
          <div class="copy-presets">
            <button class="text" data-preset="workdays" ${ed.busy ? "disabled" : ""}>Mo–Fr</button>
            <button class="text" data-preset="weekend" ${ed.busy ? "disabled" : ""}>Sa–So</button>
            <button class="text" data-preset="all" ${ed.busy ? "disabled" : ""}>Alle</button>
            <button class="text" data-preset="none" ${ed.busy ? "disabled" : ""}>Keine</button>
          </div>
        </div>
        ${ed.error ? `<div class="status error"><ha-icon icon="mdi:alert-circle-outline"></ha-icon><span>${gEsc(ed.error)}</span></div>` : ""}
        <div class="ed-actions">
          <button class="text ed-cancel" ${ed.busy ? "disabled" : ""}>Abbrechen</button>
          <button class="primary ed-save" ${ed.busy ? "disabled" : ""}>${ed.busy ? "Speichere…" : "Als Entwurf speichern"}</button>
        </div>
        <div class="ed-note">Änderungen sind ein Entwurf, bis du sie mit „Übertragen“ per Bluetooth an das Thermostat sendest.</div>
      </div>`;
  }

  _openEditor(dayKey) {
    const idx = GDAYS.findIndex(([key]) => key === dayKey);
    const segments = this._daySegments(idx).map((s) => ({ ...s }));
    this._editing = {
      day: dayKey,
      segments: segments.length ? segments : [
        { from: 0, until: 360, temp: 15 },
        { from: 360, until: 1320, temp: 21 },
        { from: 1320, until: 1440, temp: 15 },
      ],
      copyTo: new Set(),
      busy: false,
      error: null,
    };
    this._render();
  }
  _closeEditor() {
    this._editing = null;
    this._render();
  }
  _readEditorInputs() {
    const ed = this._editing;
    if (!ed) return;
    this.shadowRoot.querySelectorAll(".ed-seg").forEach((row) => {
      const seg = ed.segments[Number(row.dataset.idx)];
      const until = row.querySelector("input.ed-until");
      if (until) seg.until = gToMinutes(until.value.replace(".", ":"));
      const temp = row.querySelector("select.ed-temp");
      if (temp) seg.temp = Number(temp.value);
    });
    ed.segments.forEach((seg, idx) => {
      seg.from = idx === 0 ? 0 : ed.segments[idx - 1].until;
    });
    ed.segments[ed.segments.length - 1].until = 1440;
  }

  async _save() {
    const ed = this._editing;
    this._readEditorInputs();
    const error = gValidateDay(ed.segments);
    if (error) {
      ed.error = error;
      this._render();
      return;
    }
    const value = gSerializeDay(ed.segments);
    const ids = this._ids();
    ed.busy = true;
    ed.error = null;
    this._render();
    try {
      for (const key of [ed.day, ...ed.copyTo]) {
        const idx = GDAYS.findIndex(([k]) => k === key);
        await this._hass.callService("text", "set_value", { entity_id: ids.days[idx], value });
      }
    } catch (err) {
      ed.busy = false;
      ed.error = err?.message || String(err);
      this._render();
      return;
    }
    this._editing = null;
    this._render();
  }

  async _apply() {
    this._transfer = { busy: true, error: null };
    this._render();
    try {
      await this._hass.callService("button", "press", { entity_id: this._ids().apply });
      this._transfer = null;
    } catch (err) {
      this._transfer = { busy: false, error: `Übertragen fehlgeschlagen: ${err?.message || err}` };
    }
    this._render();
  }
  async _simple(entityId, errPrefix) {
    this._transfer = null;
    try {
      await this._hass.callService("button", "press", { entity_id: entityId });
    } catch (err) {
      this._transfer = { busy: false, error: `${errPrefix}: ${err?.message || err}` };
    }
    this._render();
  }

  _bindEvents(editable) {
    const root = this.shadowRoot;
    const menu = root.querySelector(".more-menu");
    root.querySelector(".more")?.addEventListener("click", (ev) => {
      ev.stopPropagation();
      menu.hidden = !menu.hidden;
    });
    root.querySelector("ha-card")?.addEventListener("click", () => {
      if (menu) menu.hidden = true;
    });
    root.querySelectorAll(".more-item").forEach((item) =>
      item.addEventListener("click", (ev) => {
        ev.stopPropagation();
        menu.hidden = true;
        const ids = this._ids();
        const act = item.dataset.act;
        if (act === "details") {
          this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId: ids.climate } }));
        } else if (act === "read") {
          this._simple(ids.read, "Lesen fehlgeschlagen");
        } else if (act === "toggle") {
          const on = this._st(ids.active)?.state === "on";
          this._hass.callService("switch", on ? "turn_off" : "turn_on", { entity_id: ids.active });
        }
      })
    );
    root.querySelector(".draft-apply")?.addEventListener("click", () => this._apply());
    root.querySelector(".draft-discard")?.addEventListener("click", () => this._simple(this._ids().discard, "Verwerfen fehlgeschlagen"));

    if (editable) {
      root.querySelectorAll(".day-row.editable").forEach((row) => {
        const open = () => {
          if (this._editing?.busy) return;
          const day = row.dataset.day;
          if (this._editing?.day === day) this._closeEditor();
          else this._openEditor(day);
        };
        row.addEventListener("click", open);
        row.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            open();
          }
        });
      });
    }

    const editor = root.querySelector(".editor");
    if (!editor || !this._editing) return;
    const ed = this._editing;
    editor.querySelectorAll("input.ed-until, select.ed-temp").forEach((input) =>
      input.addEventListener("change", () => {
        this._readEditorInputs();
        ed.error = null;
        this._render();
      })
    );
    editor.querySelectorAll(".ed-remove").forEach((button) =>
      button.addEventListener("click", () => {
        this._readEditorInputs();
        ed.segments.splice(Number(button.closest(".ed-seg").dataset.idx), 1);
        ed.segments.forEach((seg, i) => {
          seg.from = i === 0 ? 0 : ed.segments[i - 1].until;
        });
        ed.segments[ed.segments.length - 1].until = 1440;
        this._render();
      })
    );
    editor.querySelector(".ed-add")?.addEventListener("click", () => {
      this._readEditorInputs();
      const splitAt = (idx) => {
        const seg = ed.segments[idx];
        const mid = Math.round((seg.from + seg.until) / 2 / 5) * 5;
        if (mid <= seg.from || mid >= seg.until) return false;
        ed.segments.splice(idx + 1, 0, { from: mid, until: seg.until, temp: seg.temp });
        seg.until = mid;
        return true;
      };
      let target = ed.segments.length - 1;
      if (ed.segments[target].until - ed.segments[target].from < 10) {
        target = 0;
        ed.segments.forEach((seg, idx) => {
          const a = ed.segments[target];
          if (seg.until - seg.from > a.until - a.from) target = idx;
        });
      }
      if (!splitAt(target)) return;
      this._render();
    });
    editor.querySelectorAll("[data-copy]").forEach((box) =>
      box.addEventListener("change", () => {
        this._readEditorInputs();
        if (box.checked) ed.copyTo.add(box.dataset.copy);
        else ed.copyTo.delete(box.dataset.copy);
      })
    );
    editor.querySelectorAll("[data-preset]").forEach((button) =>
      button.addEventListener("click", () => {
        this._readEditorInputs();
        const presets = {
          workdays: ["monday", "tuesday", "wednesday", "thursday", "friday"],
          weekend: ["saturday", "sunday"],
          all: GDAYS.map(([key]) => key),
          none: [],
        };
        ed.copyTo = new Set(presets[button.dataset.preset].filter((key) => key !== ed.day));
        this._render();
      })
    );
    editor.querySelector(".ed-cancel")?.addEventListener("click", () => this._closeEditor());
    editor.querySelector(".ed-save")?.addEventListener("click", () => this._save());
    editor.addEventListener("click", (ev) => ev.stopPropagation());
  }

  _styles() {
    return `<style>
      :host { display: block; }
      ha-card { overflow: hidden; }
      .wrapper { padding: 16px; }
      .msg { padding: 16px; line-height: 1.5; }
      .header { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
      .title { font-size: 1.1rem; font-weight: 600; line-height: 1.25; }
      .subtitle { color: var(--secondary-text-color); font-size: 0.9rem; margin-top: 2px; }
      .more { margin: -8px -8px 0 0; color: var(--secondary-text-color); }
      .more-wrap { position: relative; }
      .more-menu {
        position: absolute; right: -4px; top: 32px; z-index: 5; min-width: 220px;
        display: flex; flex-direction: column; padding: 4px 0; border-radius: 10px;
        background: var(--card-background-color, #fff); box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
        border: 1px solid var(--divider-color);
      }
      .more-menu[hidden] { display: none; }
      .more-item { text-align: left; padding: 10px 14px; border: none; background: none; cursor: pointer; font: inherit; color: var(--primary-text-color); }
      .more-item:hover { background: var(--secondary-background-color); }
      .chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 4px; }
      .chip { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: 999px; font-size: 0.85rem; background: var(--secondary-background-color); color: var(--primary-text-color); }
      .chip ha-icon { --mdc-icon-size: 16px; color: var(--secondary-text-color); }
      .chip.mode { background: var(--primary-color); color: var(--text-primary-color, #fff); }
      .label .diff { margin-left: 3px; color: var(--warning-color, #ffa600); }
      .next { display: flex; align-items: center; gap: 6px; margin-top: 6px; color: var(--secondary-text-color); font-size: 0.9rem; }
      .next ha-icon, .status ha-icon { --mdc-icon-size: 18px; flex: none; }
      .status { display: flex; align-items: flex-start; gap: 8px; margin-top: 8px; padding: 8px 10px; border-radius: 10px; font-size: 0.9rem; line-height: 1.35; }
      .status.info { background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.12); }
      .status.warn { background: rgba(var(--rgb-warning-color, 255, 166, 0), 0.18); }
      .status.error { background: rgba(var(--rgb-error-color, 219, 68, 55), 0.16); }
      .draft-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }
      .axis { display: flex; justify-content: space-between; margin: 14px 0 2px 40px; font-size: 0.72rem; color: var(--secondary-text-color); }
      .days { display: grid; gap: 2px; }
      .day-row { display: grid; grid-template-columns: 32px 1fr; gap: 8px; align-items: start; padding: 4px 4px 2px; margin: 0 -4px; border-radius: 8px; }
      .day-row.editable { cursor: pointer; }
      .day-row.editable:hover, .day-row.editing { background: var(--secondary-background-color); }
      .day-row:focus-visible { outline: 2px solid var(--primary-color); }
      .label { font-weight: 600; color: var(--secondary-text-color); line-height: 26px; font-size: 0.9rem; }
      .today .label { color: var(--primary-color); }
      .bar { position: relative; height: 26px; border-radius: 6px; overflow: hidden; background: var(--secondary-background-color); }
      .seg { position: absolute; top: 0; bottom: 0; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 0.76rem; font-weight: 600; white-space: nowrap; overflow: hidden; border-right: 1px solid var(--card-background-color, #fff); box-sizing: border-box; opacity: 0.88; }
      .today .seg { opacity: 1; }
      .seg.active { box-shadow: inset 0 0 0 2px rgba(255,255,255,0.85); }
      .now { position: absolute; top: -2px; bottom: -2px; width: 2px; margin-left: -1px; background: var(--primary-text-color); box-shadow: 0 0 0 1px var(--card-background-color, #fff); }
      .empty { padding: 4px 8px; font-style: italic; color: var(--secondary-text-color); font-size: 0.85rem; }
      .times { position: relative; height: 14px; font-size: 0.68rem; color: var(--secondary-text-color); }
      .times span { position: absolute; transform: translateX(-50%); white-space: nowrap; }
      .times.two { height: 26px; }
      .times span.l1 { top: 12px; }
      .hint { margin-top: 8px; font-size: 0.78rem; color: var(--secondary-text-color); text-align: right; }
      .editor { margin: 2px 0 10px 40px; padding: 12px; border-radius: 10px; border: 1px solid var(--divider-color); background: var(--card-background-color); }
      .ed-title { font-weight: 600; margin-bottom: 8px; }
      .ed-list { display: grid; gap: 6px; }
      .ed-seg { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
      .ed-from, .ed-until.fixed { min-width: 44px; font-variant-numeric: tabular-nums; }
      .ed-dash, .ed-unit { color: var(--secondary-text-color); }
      input.ed-until { width: 4.2em; text-align: center; font-variant-numeric: tabular-nums; }
      input.ed-until, select.ed-temp { font: inherit; padding: 4px 6px; border-radius: 6px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
      button { font: inherit; cursor: pointer; border: none; border-radius: 8px; display: inline-flex; align-items: center; gap: 4px; }
      button:disabled { opacity: 0.45; cursor: default; }
      button ha-icon { --mdc-icon-size: 18px; }
      button.icon { background: none; color: var(--secondary-text-color); padding: 4px; }
      button.text { background: none; color: var(--primary-color); padding: 6px 8px; }
      button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); padding: 8px 14px; font-weight: 600; }
      .ed-add { margin-top: 6px; }
      .ed-copy { margin-top: 10px; font-size: 0.9rem; }
      .ed-copy > span { color: var(--secondary-text-color); }
      .copy-days { display: flex; flex-wrap: wrap; gap: 4px 12px; margin: 6px 0 2px; }
      .copy { display: inline-flex; align-items: center; gap: 4px; }
      .copy-presets { display: flex; flex-wrap: wrap; gap: 2px; margin-left: -8px; }
      .ed-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
      .ed-note { margin-top: 8px; font-size: 0.75rem; color: var(--secondary-text-color); }
    </style>`;
  }
}

if (!customElements.get("gira-week-profile-card")) {
  customElements.define("gira-week-profile-card", GiraWeekProfileCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "gira-week-profile-card")) {
  window.customCards.push({
    type: "gira-week-profile-card",
    name: "Gira Wochenprofil",
    description: "Wochenprogramm des Gira System 3000 Raumthermostats im Look der MAX!-Karte",
  });
}
