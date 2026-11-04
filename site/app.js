"use strict";

const REPO = "https://github.com/rohitDurbha/mcp-sentinel";
const PER_PAGE = 15;
const LEVEL_WORDS = { high: "High risk signal", medium: "Medium risk signal", cleared: "Cleared by review" };
const STATUS_WORDS = {
  ok: "Scanned successfully from its source code on the default branch.",
  no_supported_source: "Scanned, but no Python, TypeScript, JavaScript or Go source was found.",
  no_repo: "The registry lists no source repository, so there was nothing to scan.",
  unreachable: "The repository could not be reached during the last run.",
  clone_failed: "The repository could not be downloaded during the last run.",
  extract_failed: "The scanner hit an error on this repository and will retry tomorrow.",
  pending: "This repository is waiting for the next daily run.",
  stale: "The repository was unreachable today, so the last good scan is shown.",
};
const LIST_STATUS = { no_supported_source: "No supported code", no_repo: "No repository", unreachable: "Unreachable", clone_failed: "Not scanned", extract_failed: "Not scanned", pending: "Pending" };
const DISPUTE_WORDS = {
  open: "The author has disputed this result, and it stays visible with this note until a person reviews it.",
  confirmed: "A person reviewed the dispute and kept the flag in place.",
  cleared: "A person reviewed this result and cleared the flag, so it no longer counts toward any totals.",
};

/* Data */

const cache = {};
function load(name) {
  cache[name] ??= fetch(`data/${name}.json`).then((r) => {
    if (!r.ok) throw new Error(`Could not load ${name} data (HTTP ${r.status}).`);
    return r.json();
  });
  return cache[name];
}
async function servers() {
  const data = await load("servers");
  if (!data.byName) {
    const c = Object.fromEntries(data.columns.map((k, i) => [k, i]));
    data.list = data.rows.map((r) => ({
      name: r[c.name], title: r[c.title], description: r[c.description], repo: r[c.repo_url],
      subfolder: r[c.subfolder], status: r[c.status], tools: r[c.tools], flags: r[c.flags], level: r[c.level],
    }));
    for (const s of data.list) s.hay = `${s.name} ${s.title} ${s.description} ${repoShort(s.repo)}`.toLowerCase();
    data.byName = new Map(data.list.map((s) => [s.name, s]));
  }
  return data;
}

/* DOM helpers, which only ever set text so untrusted repository text cannot become markup */

function h(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) node.append(kid);
  return node;
}
const num = (n) => Number(n).toLocaleString("en-US");
const compact = (n) => new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
const repoShort = (url) => (url || "").replace(/^https:\/\/github\.com\//, "");
const flagHref = (f) => `#/flag/${f.id}`;
const serverHref = (name) => `#/server/${encodeURIComponent(name)}`;
const shownLevel = (f) => (f.dispute?.status === "cleared" ? "cleared" : f.level);
function levelTag(level) {
  return h("span", { class: `level ${level}` }, LEVEL_WORDS[level] || level);
}
const PILL_WORDS = { high: "High", medium: "Medium", cleared: "Cleared" };
const pill = (level) => h("span", { class: `level pill ${level}`, title: LEVEL_WORDS[level] }, PILL_WORDS[level] || level);
const chevron = () => h("span", { class: "chev", "aria-hidden": "true" });

const svg = (paths, size = 16) => {
  const el = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [k, v] of Object.entries({ width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 2, "stroke-linecap": "round", "aria-hidden": "true" })) el.setAttribute(k, v);
  for (const d of paths) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    el.append(path);
  }
  return el;
};
const searchIcon = () => svg(["M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Z", "m20 20-3.5-3.5"]);
const arrowIcon = () => svg(["M5 12h14", "m13 6 6 6-6 6"]);
const chevronIcon = (side) => svg([side === "left" ? "m15 6-6 6 6 6" : "m9 6 6 6-6 6"]);

// A search field with an icon and a slash shortcut, after the inputs on 21st.dev and uiverse.
const searchField = (input) => h("label", { class: "field" }, searchIcon(), input, h("kbd", { "aria-hidden": "true" }, "/"));

// Radio buttons drawn as a segmented control. Returns the element and a reader for its value.
function segmented(name, options, onChange) {
  const el = h("div", { class: "segmented", role: "radiogroup", "aria-label": name });
  for (const [value, label] of options) {
    el.append(h("label", {}, h("input", { type: "radio", name, value, checked: value === "", onchange: onChange }), h("span", {}, label)));
  }
  return { el, value: () => el.querySelector("input:checked").value };
}

// Primary action after Magic UI's InteractiveHoverButton (MIT).
const action = (href, text) => h("a", { class: "action", href },
  h("span", { class: "dot", "aria-hidden": "true" }), h("span", { class: "label" }, text),
  h("span", { class: "hover", "aria-hidden": "true" }, text, arrowIcon()));

// Counts up once when the number scrolls into view, after Magic UI's NumberTicker (MIT).
function ticker(value) {
  const el = h("b", { style: `min-width:${num(value).length}ch` }, num(value));
  if (matchMedia("(prefers-reduced-motion: reduce)").matches || !("IntersectionObserver" in window)) return el;
  el.textContent = "0";
  const seen = new IntersectionObserver(([entry]) => {
    if (!entry.isIntersecting) return;
    seen.disconnect();
    const start = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - start) / 1400);
      el.textContent = num(Math.round(value * (1 - (1 - k) ** 4)));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
  seen.observe(el);
  return el;
}
const reveal = (el, i) => {
  el.classList.add("reveal");
  el.style.setProperty("--i", i);
  return el;
};
function day(iso) {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

/* Evidence highlighting. Offsets come from Python, which counts code points, so slice by code point. */
function marked(text, spans, cls = "quoted") {
  const chars = Array.from(text || "");
  const merged = [];
  for (const [s, e] of [...spans].sort((a, b) => a[0] - b[0])) {
    const last = merged[merged.length - 1];
    if (last && s <= last[1]) last[1] = Math.max(last[1], e);
    else merged.push([s, e]);
  }
  const out = h("p", { class: cls });
  let at = 0;
  for (const [s, e] of merged) {
    out.append(chars.slice(at, s).join(""), h("mark", { style: `--i:${out.childElementCount}` }, chars.slice(s, e).join("")));
    at = e;
  }
  out.append(chars.slice(at).join(""));
  return out;
}
const spansFor = (flag, field) => flag.findings.filter((f) => f.field === field).map((f) => [f.start, f.end]);

/* Shared pieces */

function flagRow(f) {
  const first = f.findings[0];
  const reason = first ? first.message : "The classifier flagged this text.";
  const where = f.servers.length > 1 ? `${f.servers.length} registry entries` : "1 registry entry";
  return h("li", {}, h("a", { class: "row", href: flagHref(f) },
    pill(shownLevel(f)),
    h("span", { class: "name" }, f.name),
    h("span", { class: "side" }, where),
    chevron(),
    h("span", { class: "sub" }, `${reason}. In ${repoShort(f.repo_url)}.`),
  ));
}

// A short page of rows with a pager underneath, so long result sets never become one long scroll.
function pagedList(container, items, render, emptyText) {
  container.replaceChildren();
  if (!items.length) {
    container.append(h("p", { class: "empty", "aria-live": "polite" }, emptyText));
    return;
  }
  const pages = Math.ceil(items.length / PER_PAGE);
  const list = h("ol", { class: "rows" });
  const range = h("p", { class: "range", "aria-live": "polite" });
  const nav = h("nav", { class: "pager", "aria-label": "Pages" });
  const go = (page) => () => {
    show(page);
    if (container.getBoundingClientRect().top < 0) container.scrollIntoView({ block: "start" });
  };
  const button = (label, page, attrs = {}) => h("button", { type: "button", onclick: go(page), ...attrs }, label);
  const show = (page) => {
    const first = (page - 1) * PER_PAGE;
    list.replaceChildren(...items.slice(first, first + PER_PAGE).map(render));
    range.textContent = `${num(first + 1)}\u2013${num(Math.min(first + PER_PAGE, items.length))} of ${num(items.length)}`;
    const numbers = [];
    for (let n = 1; n <= pages; n++) {
      if (n === 1 || n === pages || Math.abs(n - page) <= 1) numbers.push(n);
      else if (numbers.at(-1) !== "gap") numbers.push("gap");
    }
    nav.replaceChildren(
      button(chevronIcon("left"), page - 1, { class: "step", "aria-label": "Previous page", disabled: page === 1 }),
      ...numbers.map((n) => (n === "gap"
        ? h("span", { class: "gap", "aria-hidden": "true" }, "\u2026")
        : button(num(n), n, { class: "num", "aria-label": `Page ${n}`, "aria-current": n === page ? "page" : null }))),
      h("span", { class: "of" }, `Page ${page} of ${pages}`),
      button(chevronIcon("right"), page + 1, { class: "step", "aria-label": "Next page", disabled: page === pages }),
    );
  };
  show(1);
  container.append(list, h("div", { class: "pager-bar" }, range, pages > 1 ? nav : null));
}

/* The specimen reel. Real flagged tools play one after another, and each one walks through
   the scan as it happens. A scan line passes over the text, the rule matches are marked in
   order, the classifier meter fills to its score, and then the result appears. */

const SPECIMENS = 6;
const SPECIMEN_CHARS = 520;

// Four tools that both the rules and the classifier flagged, then two that only the classifier
// caught, each from a different repository and short enough to read in a few seconds.
function specimenPool(flags) {
  const short = (f) => f.description && Array.from(f.description).length <= SPECIMEN_CHARS;
  const strongest = (a, b) => b.model.score - a.model.score || a.id.localeCompare(b.id);
  const seen = new Set();
  const take = (list, n) => list.filter((f) => !seen.has(f.repo_url) && seen.add(f.repo_url)).slice(0, n);
  const both = take(flags.filter((f) => f.level === "high" && f.model?.flag && spansFor(f, "description").length && short(f)).sort(strongest), 4);
  const modelOnly = take(flags.filter((f) => !f.findings.length && f.model?.flag && short(f)).sort(strongest), SPECIMENS - both.length);
  return [both[0], both[1], modelOnly[0], both[2], both[3], modelOnly[1]].filter(Boolean);
}

function specimenSlide(f, i, total) {
  const marks = spansFor(f, "description").length;
  const rules = [...new Map(f.findings.map((x) => [x.rule, x])).values()];
  const scan = 1100, step = 320;
  const after = scan + Math.max(marks, rules.length) * step;
  const terms = (f.model?.top_terms || []).slice(0, 3).map((t) => `\u201c${t[0]}\u201d`);
  const text = marked(f.description, spansFor(f, "description"));
  text.classList.add("specimen-text");
  const slide = h("article", { class: "slide", "aria-roledescription": "slide", "aria-label": `${i + 1} of ${total}`,
    style: `--scan:${scan}ms;--step:${step}ms;--after:${after}ms;--dur:${after + 4200}ms` },
    h("p", { class: "who" }, "From the tool ", h("code", {}, f.name), ` in ${repoShort(f.repo_url)}`),
    h("div", { class: "specimen-body" }, text, h("span", { class: "scanline", "aria-hidden": "true" })),
    h("dl", { class: "verdict" },
      h("div", {}, h("dt", {}, "Rules"), h("dd", { class: "rule-chips" }, rules.length
        ? rules.map((x, n) => h("span", { class: `rule-chip ${x.severity}`, style: `--i:${n}`, title: x.rule }, x.message))
        : h("span", { class: "rule-chip none", style: "--i:0" }, "No rule matched this text"))),
      h("div", {}, h("dt", {}, "Classifier"), h("dd", { class: "meter-row" },
        h("span", { class: "meter", role: "img", "aria-label": `Classifier score ${f.model.score.toFixed(2)} out of 1` },
          h("span", { class: "meter-fill", style: `--score:${f.model.score}` })),
        h("span", { class: "meter-text" }, `${f.model.score.toFixed(2)}, ${f.model.flag ? "flagged" : "below its threshold"}`,
          terms.length ? `, leaning on ${terms.slice(0, -1).join(", ")}${terms.length > 1 ? " and " : ""}${terms.at(-1)}` : ""))),
      h("div", { class: "result" }, h("dt", {}, "Result"), h("dd", {}, levelTag(f.level), h("a", { href: flagHref(f) }, "See the evidence"))),
    ),
  );
  return slide;
}

function specimenReel(pool) {
  const slides = pool.map((f, i) => specimenSlide(f, i, pool.length));
  const counter = h("span", { class: "reel-count", "aria-hidden": "true" });
  const progress = h("span", { class: "reel-progress", "aria-hidden": "true" });
  const playLabel = () => (reel.classList.contains("stopped") ? "Play the examples" : "Pause the examples");
  const playIcon = () => (reel.classList.contains("stopped") ? svg(["M8 5v14l11-7z"]) : svg(["M9 5v14", "M15 5v14"]));
  const play = h("button", { type: "button", class: "reel-btn" });
  const button = (label, icon, onclick) => h("button", { type: "button", class: "reel-btn", "aria-label": label, onclick }, icon);
  const reel = h("section", { class: "specimen reel", "aria-roledescription": "carousel", "aria-label": "How the scan reads a tool" },
    h("div", { class: "reel-bar" }, counter,
      button("Previous example", chevronIcon("left"), () => show(at - 1)),
      play,
      button("Next example", chevronIcon("right"), () => show(at + 1))),
    h("div", { class: "slides" }, slides), progress);
  let at = 0;
  const show = (n) => {
    at = (n + slides.length) % slides.length;
    slides.forEach((s, i) => {
      s.classList.toggle("active", i === at);
      s.toggleAttribute("inert", i !== at);
      s.setAttribute("aria-hidden", String(i !== at));
    });
    counter.textContent = `${at + 1} of ${slides.length}`;
    progress.style.setProperty("--dur", slides[at].style.getPropertyValue("--dur"));
    progress.classList.remove("run");
    void progress.offsetWidth;  // a reflow between the two class changes restarts the timer
    progress.classList.add("run");
  };
  const syncPlay = () => {
    play.setAttribute("aria-label", playLabel());
    play.replaceChildren(playIcon());
  };
  play.addEventListener("click", () => {
    reel.classList.toggle("stopped");
    syncPlay();
  });
  progress.addEventListener("animationend", () => show(at + 1));
  // The timer pauses while someone reads or tabs inside, and while the reel is off screen.
  reel.addEventListener("pointerenter", () => reel.classList.add("held"));
  reel.addEventListener("pointerleave", () => reel.classList.remove("held"));
  reel.addEventListener("focusin", () => reel.classList.add("held"));
  reel.addEventListener("focusout", (e) => { if (!reel.contains(e.relatedTarget)) reel.classList.remove("held"); });
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(([e]) => reel.classList.toggle("offscreen", !e.isIntersecting)).observe(reel);
  }
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) reel.classList.add("stopped");
  syncPlay();
  show(0);
  return reel;
}

/* Insights. Linked bar charts over the flagged tools, where a click on any bar filters every
   other chart and the list of matching tools. Each chart ignores its own filter, so the other
   choices stay visible while one is picked. */

const SIGNAL_NAMES = {
  secrecy: "Secrecy from the user", sensitive_path: "Sensitive files", hidden_block: "Hidden instructions",
  exfiltration: "Sending data out", override: "Instruction override", long_text: "Unusually long text",
  cross_tool: "Steering other tools", coercion: "Pressure to act first", invisible_unicode: "Invisible characters",
};
const CAUGHT_NAMES = { both: "Rules and classifier", rules: "Rules only", model: "Classifier only" };
const WHERE_NAMES = { description: "Description", param: "Parameters", both: "Description and parameters", none: "No rule match" };
const OUTCOME_NAMES = {
  ok: "Scanned, tools found", no_supported_source: "No supported source code", no_repo: "No repository listed",
  unreachable: "Repository unreachable", clone_failed: "Download failed", extract_failed: "Scanner error",
  pending: "Queued for the next run", stale: "Last good scan reused",
};
const pct = (part, whole) => `${whole ? ((100 * part) / whole).toFixed(part / whole < 0.01 ? 2 : 1) : 0}%`;

function traits(f) {
  const rules = f.rule_level === "medium" || f.rule_level === "high";
  const model = Boolean(f.model?.flag);
  const fields = new Set(f.findings.map((x) => (x.field.startsWith("param:") ? "param" : "description")));
  return {
    level: f.level,
    signal: [...new Set(f.findings.map((x) => x.signal))],
    rule: [...new Set(f.findings.map((x) => x.rule))],
    caught: rules && model ? "both" : rules ? "rules" : "model",
    where: fields.size === 2 ? "both" : fields.size ? [...fields][0] : "none",
    bin: Math.min(9, Math.floor((f.model?.score ?? 0) * 10)),
    repo: repoShort(f.repo_url),
  };
}

function insights(flags, summary) {
  const items = flags.map((f) => ({ f, t: traits(f) }));
  const ruleNames = new Map(flags.flatMap((f) => f.findings.map((x) => [x.rule, x.message])));
  const picked = {};
  const has = (t, dim, value) => (Array.isArray(t[dim]) ? t[dim].includes(value) : t[dim] === value);
  const matching = (except) => items.filter(({ t }) =>
    Object.entries(picked).every(([dim, value]) => dim === except || has(t, dim, value)));
  const pick = (dim, value) => {
    if (picked[dim] === value) delete picked[dim];
    else picked[dim] = value;
    update();
  };

  // One bar per row, stacked by level when the bars count flagged tools.
  const bars = (dim, rows, { stacked = true, clickable = true } = {}) => {
    const max = Math.max(1, ...rows.map((r) => r.total));
    return h("div", { class: `bars${dim in picked ? " has-pick" : ""}` }, rows.map((r) => {
      const fills = stacked
        ? [["high", r.high], ["medium", r.medium]].filter(([, n]) => n).map(([lvl, n]) => h("span", { class: `fill ${lvl}`, style: `width:${(100 * n) / max}%` }))
        : [h("span", { class: "fill", style: `width:${(100 * r.total) / max}%` })];
      const tip = stacked ? `${r.label}. ${num(r.total)} tools, ${num(r.high)} high and ${num(r.medium)} medium.` : `${r.label}. ${num(r.total)} entries, ${r.share}.`;
      const kids = [h("span", { class: "bar-label" }, r.label), h("span", { class: "bar-value" }, stacked ? num(r.total) : `${num(r.total)}  ${r.share}`), h("span", { class: "bar-track" }, fills)];
      return clickable
        ? h("button", { type: "button", class: "bar", "data-tip": tip, "aria-pressed": String(picked[dim] === r.key), onclick: () => pick(dim, r.key) }, kids)
        : h("div", { class: "bar static", "data-tip": tip }, kids);
    }));
  };
  const count = (dim, keys, label) => {
    const pool = matching(dim);
    return keys.map((key) => {
      const hits = pool.filter(({ t }) => has(t, dim, key));
      const high = hits.filter(({ t }) => t.level === "high").length;
      return { key, label: label(key), total: hits.length, high, medium: hits.length - high };
    });
  };
  const top = (dim, n, label) => {
    const tally = new Map();
    for (const { t } of matching(dim)) for (const v of [t[dim]].flat()) tally.set(v, (tally.get(v) || 0) + 1);
    const keys = [...tally].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0]))).slice(0, n).map(([k]) => k);
    if (dim in picked && !keys.includes(picked[dim])) keys.push(picked[dim]);
    return count(dim, keys, label);
  };
  const sortedKeys = (dim) => {
    const totals = new Map();
    for (const { t } of items) for (const v of [t[dim]].flat()) totals.set(v, (totals.get(v) || 0) + 1);
    return [...totals].sort((a, b) => b[1] - a[1]).map(([k]) => k);
  };

  const histogram = () => {
    const rows = count("bin", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], (b) => `Score ${(b / 10).toFixed(1)} to ${((b + 1) / 10).toFixed(1)}`);
    const max = Math.max(1, ...rows.map((r) => r.total));
    return h("div", {},
      h("div", { class: `hist${"bin" in picked ? " has-pick" : ""}` }, rows.map((r) => h("button", {
        type: "button", class: "col", "aria-pressed": String(picked.bin === r.key), "aria-label": `${r.label}, ${r.total} tools`,
        "data-tip": `${r.label}. ${num(r.total)} tools, ${num(r.high)} high and ${num(r.medium)} medium.`, onclick: () => pick("bin", r.key),
      }, [["high", r.high], ["medium", r.medium]].filter(([, n]) => n).map(([lvl, n]) => h("span", { class: `seg ${lvl}`, style: `height:${(100 * n) / max}%` }))))),
      h("div", { class: "hist-axis", "aria-hidden": "true" }, h("span", {}, "0"), h("span", {}, "0.5"), h("span", {}, "1")));
  };

  const level = segmented("Insight level", [["", "All"], ["high", "High"], ["medium", "Medium"]], () => {
    const v = level.value();
    if (v) picked.level = v;
    else delete picked.level;
    update();
  });
  const chips = h("div", { class: "chips", "aria-live": "polite" });
  const grid = h("div", { class: "insights" });
  const list = h("div", { class: "results" });
  const card = (title, body, wide) => h("section", { class: `card${wide ? " wide" : ""}` }, h("h3", {}, title), body);
  const LABELS = {
    signal: (k) => SIGNAL_NAMES[k] || k, rule: (k) => ruleNames.get(k) || k, caught: (k) => CAUGHT_NAMES[k],
    where: (k) => WHERE_NAMES[k], repo: (k) => k, bin: (k) => `Classifier score ${(k / 10).toFixed(1)} to ${((k + 1) / 10).toFixed(1)}`,
  };

  function update() {
    const shown = matching();
    chips.replaceChildren(
      h("span", { class: "chips-count" }, `${num(shown.length)} of ${num(items.length)} flagged tools`),
      ...Object.entries(picked).filter(([dim]) => dim !== "level").map(([dim, value]) =>
        h("button", { type: "button", class: "chip-x", "aria-label": `Remove filter ${LABELS[dim](value)}`, onclick: () => pick(dim, value) }, LABELS[dim](value), h("span", { "aria-hidden": "true" }, "×"))),
      Object.keys(picked).length ? h("button", { type: "button", class: "clear", onclick: () => {
        for (const k of Object.keys(picked)) delete picked[k];
        level.el.querySelector('input[value=""]').checked = true;
        update();
      } }, "Clear filters") : "",
    );
    grid.replaceChildren(
      card("Signal family", bars("signal", count("signal", sortedKeys("signal"), LABELS.signal))),
      card("Most common rules", bars("rule", top("rule", 8, LABELS.rule))),
      card("How it was caught", bars("caught", count("caught", ["both", "rules", "model"], LABELS.caught))),
      card("Where the evidence sits", bars("where", count("where", sortedKeys("where"), LABELS.where))),
      card("Classifier score", histogram()),
      card("Repositories with the most flags", bars("repo", top("repo", 8, LABELS.repo))),
    );
    pagedList(list, shown.map(({ f }) => f), flagRow, "No flagged tool matches every filter. Remove one to widen the view.");
  }

  const jobs = Object.entries(summary.jobs || {}).sort((a, b) => b[1] - a[1]);
  const totalJobs = jobs.reduce((n, [, v]) => n + v, 0);
  const outcomes = bars("outcome", jobs.map(([key, total]) => ({ key, total, label: OUTCOME_NAMES[key] || key, share: pct(total, totalJobs) })), { stacked: false, clickable: false });

  const section = h("section", { class: "insight-section", "aria-labelledby": "inside" },
    h("h2", { id: "inside" }, "Inside the scan"),
    h("div", { class: "insights" }, card(`What happened to ${num(totalJobs)} registry entries`, outcomes, true)),
    h("h3", { class: "explore" }, "Explore the flags"),
    h("div", { class: "filterbar" }, level.el, chips, h("span", { class: "legend-mini", "aria-hidden": "true" }, pill("high"), pill("medium"))),
    grid, list);

  const tip = h("div", { class: "floattip", role: "tooltip", hidden: true });
  section.append(tip);
  const place = (target, x, y) => {
    tip.textContent = target.dataset.tip;
    tip.hidden = false;
    const box = section.getBoundingClientRect();
    const left = Math.min(Math.max(x - box.left + 14, 0), box.width - tip.offsetWidth);
    tip.style.transform = `translate(${left}px, ${y - box.top + 16}px)`;
  };
  section.addEventListener("pointermove", (e) => {
    const target = e.target.closest?.("[data-tip]");
    if (target && e.pointerType === "mouse") place(target, e.clientX, e.clientY);
    else tip.hidden = true;
  });
  section.addEventListener("pointerleave", () => { tip.hidden = true; });
  section.addEventListener("focusin", (e) => {
    const target = e.target.closest?.("[data-tip]");
    if (!target) return;
    const r = target.getBoundingClientRect();
    place(target, r.left, r.bottom - 8);
  });
  section.addEventListener("focusout", () => { tip.hidden = true; });
  update();
  return section;
}

/* Trend chart. One y axis, thin lines, markers, direct labels, a legend, hover and a table. */

function lineChart({ title, series, format = num }) {
  const fig = h("figure", { class: "chart" }, h("figcaption", {}, title));
  const xs = [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))].sort();
  if (!xs.length) {
    fig.append(h("p", { class: "empty" }, "This chart fills in as the daily runs record it."));
    return fig;
  }
  const plot = h("div", { class: "plot" });
  fig.append(plot);
  if (series.length > 1) {
    fig.append(h("p", { class: "muted" }, ...series.map((s, i) => [
      i ? "  " : "", h("span", { style: `color:${s.color}`, "aria-hidden": "true" }, "■ "), s.name,
    ])));
  }
  const draw = () => {
    const W = Math.max(plot.clientWidth, 280), H = 200, L = 52, R = series.length > 1 ? 70 : 16, T = 12, B = 28;
    const maxY = Math.max(1, ...series.flatMap((s) => s.points.map((p) => p.y)));
    const t = xs.map((x) => Date.parse(x));
    const t0 = Math.min(...t), t1 = Math.max(...t);
    const X = (x) => (t1 === t0 ? (L + W - R) / 2 : L + ((Date.parse(x) - t0) / (t1 - t0)) * (W - L - R));
    const Y = (y) => T + (1 - y / maxY) * (H - T - B);
    const ns = "http://www.w3.org/2000/svg";
    const s = (tag, attrs, text) => {
      const el = document.createElementNS(ns, tag);
      for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
      if (text != null) el.textContent = text;
      return el;
    };
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": title });
    for (const v of [0, maxY / 2, maxY]) {
      svg.append(s("line", { class: "axis", x1: L, x2: W - R, y1: Y(v), y2: Y(v) }));
      svg.append(s("text", { x: L - 8, y: Y(v) + 4, "text-anchor": "end" }, compact(v)));
    }
    const labels = [...new Set(xs.map(day))];
    const ticks = labels.length > 1 ? [xs[0], xs[xs.length - 1]] : [xs[0]];
    for (const x of ticks) svg.append(s("text", { x: X(x), y: H - 8, "text-anchor": "middle" }, day(x)));
    for (const ser of series) {
      const pts = ser.points.map((p) => `${X(p.x)},${Y(p.y)}`).join(" ");
      if (ser.points.length > 1) svg.append(s("polyline", { points: pts, fill: "none", stroke: ser.color, "stroke-width": 2 }));
      for (const p of ser.points) svg.append(s("circle", { cx: X(p.x), cy: Y(p.y), r: 4, fill: ser.color, stroke: "var(--paper)", "stroke-width": 2 }));
      const last = ser.points[ser.points.length - 1];
      if (series.length > 1 && last) svg.append(s("text", { class: "label", x: X(last.x) + 10, y: Y(last.y) + 4 }, ser.name));
    }
    const cross = s("line", { class: "cross", y1: T, y2: H - B, visibility: "hidden" });
    svg.append(cross);
    const tip = h("div", { class: "tip", hidden: true });
    svg.addEventListener("pointermove", (e) => {
      const box = svg.getBoundingClientRect();
      const px = ((e.clientX - box.left) / box.width) * W;
      const x = xs.reduce((a, b) => (Math.abs(X(b) - px) < Math.abs(X(a) - px) ? b : a));
      cross.setAttribute("x1", X(x)); cross.setAttribute("x2", X(x)); cross.setAttribute("visibility", "visible");
      tip.replaceChildren(h("b", {}, day(x)), ...series.map((ser) => {
        const p = ser.points.find((q) => q.x === x);
        return h("div", {}, `${ser.name} ${p ? format(p.y) : "not recorded"}`);
      }));
      tip.hidden = false;
      const share = X(x) / W;  // keep the tip inside the plot near either edge
      tip.style.left = `${share * 100}%`;
      tip.style.top = `${T + 8}px`;
      tip.style.transform = `translateX(${share > 0.6 ? "calc(-100% - 10px)" : share < 0.4 ? "10px" : "-50%"})`;
    });
    svg.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; });
    plot.replaceChildren(svg, tip);
  };
  requestAnimationFrame(draw);
  new ResizeObserver(() => draw()).observe(plot);
  const table = h("table", {}, h("tr", {}, h("th", {}, "Run"), ...series.map((ser) => h("th", {}, ser.name))),
    ...xs.map((x) => h("tr", {}, h("td", {}, new Date(x).toISOString().replace("T", " ").slice(0, 16) + " UTC"),
      ...series.map((ser) => h("td", {}, format(ser.points.find((p) => p.x === x)?.y ?? "")))),
    ));
  fig.append(h("details", {}, h("summary", {}, "Show the numbers as a table"), table));
  return fig;
}

/* Views */

async function viewHome(main) {
  const [flags, summary, history] = await Promise.all([load("flags"), load("summary"), load("history")]);
  const counted = flags.filter((f) => shownLevel(f) !== "cleared");
  const highs = counted.filter((f) => f.level === "high").length;
  const pool = specimenPool(counted);

  main.append(
    reveal(h("h1", {}, "Hidden instructions in MCP tool descriptions, checked every day."), 0),
    reveal(h("p", { class: "lede" },
      "AI assistants read the description of every tool they can call, and that text can quietly steer them. ",
      "This site reads the source code behind each public server in the official MCP registry and marks the exact words that look like instructions aimed at the assistant."), 1),
  );
  if (pool.length) main.append(reveal(specimenReel(pool), 2));
  main.append(reveal(h("ul", { class: "facts" },
    h("li", {}, ticker(summary.servers), h("span", {}, "registry entries")),
    h("li", {}, ticker(summary.repos_checked), h("span", {}, "repositories checked")),
    h("li", {}, ticker(summary.tools_unique), h("span", {}, "distinct tools read")),
    h("li", {}, ticker(counted.length), h("span", {}, `flagged, ${num(highs)} of them high`)),
  ), 4));

  main.append(h("h2", { id: "flags" }, "Every flagged tool"),
    h("p", { class: "muted" }, "Each flag is an automated risk signal that deserves a human look. Many are harmless phrasing or security demos, and authors can dispute any result."));
  const signals = [...new Set(flags.flatMap((f) => f.findings.map((x) => x.signal)))].sort();
  const q = h("input", { type: "search", placeholder: "Tool, repository or phrase", "aria-label": "Filter flagged tools" });
  const lvl = segmented("Level", [["", "All"], ["high", "High"], ["medium", "Medium"], ["cleared", "Cleared"]], () => apply());
  const sig = h("select", { "aria-label": "Signal" }, h("option", { value: "" }, "All signals"),
    ...signals.map((s) => h("option", { value: s }, s.replaceAll("_", " "))), h("option", { value: "model" }, "classifier only"));
  const list = h("div", { class: "results" });
  const order = { high: 0, medium: 1, cleared: 2 };
  const sorted = [...flags].sort((a, b) => order[shownLevel(a)] - order[shownLevel(b)] || b.rule_score - a.rule_score || a.name.localeCompare(b.name));
  const apply = () => {
    const needle = q.value.trim().toLowerCase();
    const hits = sorted.filter((f) =>
      (!lvl.value() || shownLevel(f) === lvl.value()) &&
      (!sig.value || (sig.value === "model" ? !f.findings.length : f.findings.some((x) => x.signal === sig.value))) &&
      (!needle || `${f.name} ${f.repo_url} ${f.description}`.toLowerCase().includes(needle)));
    pagedList(list, hits, flagRow, "No flagged tool matches these filters. Try a broader phrase or another level.");
  };
  for (const el of [q, sig]) el.addEventListener("input", apply);
  main.append(h("div", { class: "controls" }, searchField(q), lvl.el, h("span", { class: "select" }, sig)), list);
  apply();

  const runs = history.map((r) => r.generated_at);
  main.append(insights(counted, summary));
  main.append(h("h2", {}, "Over time"), h("div", { class: "charts" },
    lineChart({
      title: "Distinct flagged tools by level",
      series: [
        { name: "High", color: "var(--high)", points: history.filter((r) => r.flagged_unique).map((r) => ({ x: r.generated_at, y: r.flagged_unique.high })) },
        { name: "Medium", color: "var(--medium)", points: history.filter((r) => r.flagged_unique).map((r) => ({ x: r.generated_at, y: r.flagged_unique.medium })) },
      ],
    }),
    lineChart({
      title: "Distinct tools read per run",
      series: [{ name: "Tools", color: "var(--link)", points: history.filter((r) => r.tools_unique).map((r) => ({ x: r.generated_at, y: r.tools_unique })) }],
    }),
  ), h("p", { class: "muted" }, `The history holds ${num(runs.length)} daily runs so far, and each new run adds a point.`));
}

async function viewServers(main, params) {
  main.append(h("h1", {}, "Look up any server in the registry"),
    h("p", { class: "lede" }, "Search by registry name, title, description or repository to see what the scan found."));
  const q = h("input", { type: "search", placeholder: "For example postgres or github.com/owner", value: params.get("q") || "", "aria-label": "Search servers" });
  const onlyFlagged = h("input", { type: "checkbox", checked: params.get("flagged") === "1" });
  const count = h("p", { class: "count", "aria-live": "polite" }, "Loading the server index, which takes a moment on slow connections.");
  const list = h("div", { class: "results" });
  main.append(h("div", { class: "controls" }, searchField(q),
    h("label", { class: "toggle" }, onlyFlagged, "Only servers with flags")), count, list);
  const data = await servers();
  count.remove();
  const render = (s) => h("li", {}, h("a", { class: "row", href: serverHref(s.name) },
    s.flags ? pill(s.level) : h("span", { class: "side pill-slot" }, LIST_STATUS[s.status] ?? `${num(s.tools)} tools`),
    h("span", { class: "name" }, s.name),
    h("span", { class: "side" }, s.flags ? `${s.flags} flagged` : ""),
    chevron(),
    h("span", { class: "sub" }, s.description || s.title || repoShort(s.repo) || "No description in the registry."),
  ));
  const rank = { high: 0, medium: 1, none: 2 };
  const apply = () => {
    const needle = q.value.trim().toLowerCase();
    let hits = data.list.filter((s) => (!onlyFlagged.checked || s.flags) && (!needle || s.hay.includes(needle)));
    if (!needle) hits = [...hits].sort((a, b) => rank[a.level] - rank[b.level] || b.flags - a.flags || a.name.localeCompare(b.name));
    pagedList(list, hits, render, "No registry entry matches that search. Try part of the name or the repository owner.");
    const next = new URLSearchParams({ ...(needle && { q: q.value.trim() }), ...(onlyFlagged.checked && { flagged: "1" }) });
    history.replaceState(null, "", `#/servers${next.size ? `?${next}` : ""}`);
  };
  q.addEventListener("input", apply);
  onlyFlagged.addEventListener("change", apply);
  apply();
  q.focus();
}

async function viewServer(main, name) {
  const [data, flags] = await Promise.all([servers(), load("flags")]);
  const s = data.byName.get(name);
  if (!s) return notFound(main, "No registry entry by that name appeared in the latest scan.");
  const mine = flags.filter((f) => f.servers.includes(name));
  const repoLink = s.repo ? h("a", { href: s.subfolder ? `${s.repo}/tree/HEAD/${s.subfolder}` : s.repo }, repoShort(s.repo) + (s.subfolder ? `/${s.subfolder}` : "")) : "None listed";
  main.append(
    h("h1", { class: "tool" }, s.name),
    s.description ? h("p", { class: "lede" }, s.description) : null,
    h("dl", { class: "meta" },
      h("dt", {}, "Source"), h("dd", {}, repoLink),
      h("dt", {}, "Scan result"), h("dd", {}, STATUS_WORDS[s.status] || s.status || "Not scanned."),
      h("dt", {}, "Tools found"), h("dd", {}, num(s.tools)),
      h("dt", {}, "Flagged tools"), h("dd", {}, s.flags ? num(s.flags) : "None"),
      s.flags ? [h("dt", {}, "Highest level"), h("dd", {}, levelTag(s.level))] : null,
    ),
    h("h2", {}, "Flagged tools in this server"),
  );
  const list = h("div", { class: "results" });
  main.append(list);
  pagedList(list, mine, flagRow, s.status === "ok"
    ? "None of the tools in this server tripped a rule or the classifier in the latest scan."
    : "Nothing was flagged, because the latest run could not read tool text for this entry.");
}

async function viewFlag(main, id) {
  const flags = await load("flags");
  const f = flags.find((x) => x.id === id);
  if (!f) return notFound(main, "That flag is not in the latest scan, which usually means the tool text changed.");
  const level = shownLevel(f);
  const disputeUrl = `${REPO}/issues/new?${new URLSearchParams({
    template: "dispute.yml", title: `Dispute ${f.name} in ${repoShort(f.repo_url)}`, flag: f.id, tool: `${f.name} at ${f.source_url}`,
  })}`;
  main.append(
    h("p", {}, levelTag(level)),
    h("h1", { class: "tool" }, f.name),
    h("p", { class: "muted" }, "This is an automated risk signal about the text below. It does not say anything about the intent of the server or its author."),
  );
  if (f.dispute) {
    main.append(h("div", { class: "note" }, h("p", {}, DISPUTE_WORDS[f.dispute.status], f.dispute.note ? ` ${f.dispute.note}` : "",
      f.dispute.issue ? [" ", h("a", { href: f.dispute.issue }, "Read the discussion.")] : "")));
  }
  main.append(h("dl", { class: "meta" },
    h("dt", {}, "Source"), h("dd", {}, h("a", { href: f.source_url }, `${f.path} line ${f.line}`), ` in ${repoShort(f.repo_url)} at commit `, h("code", {}, f.commit.slice(0, 7))),
    h("dt", {}, "Registry entries"), h("dd", {}, ...f.servers.flatMap((n, i) => [i ? ", " : "", h("a", { href: serverHref(n) }, n)])),
  ));
  main.append(h("h2", {}, "Tool description"),
    f.description ? marked(f.description, spansFor(f, "description"), "quoted small") : h("p", { class: "muted" }, "This tool has no description."));
  const params = f.params.filter((p) => p.text);
  if (params.length) {
    main.append(h("h2", {}, "Parameter descriptions"), ...params.map((p) => h("div", { class: "param" },
      h("span", { class: "mono" }, p.name || "input"), marked(p.text, spansFor(f, `param:${p.name || ""}`), "quoted small"))));
  }
  main.append(h("h2", {}, "Why it was flagged"));
  const reasons = h("ul", { class: "reasons" }, ...f.findings.map((x) => h("li", {},
    h("b", {}, x.message), `. The rule `, h("code", {}, x.rule), ` in the ${x.signal.replaceAll("_", " ")} family matched `,
    h("mark", {}, x.evidence), x.field === "description" ? " in the description." : ` in the ${x.field.replace("param:", "")} parameter.`)));
  const m = f.model;
  if (m) {
    const terms = (m.top_terms || []).map((t) => t[0]).join(", ");
    reasons.append(h("li", {}, m.flag
      ? [h("b", {}, "The classifier flagged this text too"), `. Its score was ${m.score}, and the words that pushed it highest were ${terms || "not recorded"}.`]
      : `The classifier scored this text ${m.score}, which is below its threshold, so the level comes from the rules alone.`));
  }
  main.append(reasons,
    h("h2", {}, "Think this is wrong?"),
    h("p", {}, "If you maintain this server and the text is harmless, open a dispute. The flag stays visible with a note until a person reviews it and either confirms or clears it."),
    action(disputeUrl, "Dispute this result on GitHub"));
}

function viewMethod(main) {
  const p = (...t) => h("p", {}, ...t);
  main.append(
    h("h1", {}, "How the scan works"),
    p("Every day a scheduled job pulls the full list of servers from the official MCP registry and checks the latest commit of each linked repository. Only repositories that changed since the previous day are downloaded again, and the rest reuse their earlier results."),
    p("The scanner never runs, installs or imports anything from these repositories. It reads Python, TypeScript, JavaScript and Go files as plain syntax trees and pulls out each tool name, description and parameter description, including text assembled from constants."),
    h("h2", {}, "Rules and the classifier"),
    p("Explainable rules look for patterns that published attacks rely on. These include instruction tags such as IMPORTANT blocks, requests to keep something from the user, paths to secret files like SSH keys, places to send data, invisible characters and text that tries to steer other tools. Every match records the exact words and where they sit."),
    p("A logistic regression classifier also reads each description. It was trained on synthetic attacks inserted into real harmless descriptions, and it is tested only on real attacks that it never saw during training. Its threshold aims for about one false alarm in every hundred harmless tools, and the ",
      h("a", { href: `${REPO}/blob/main/docs/model_card.md` }, "model card"), " records its measured accuracy and known weak spots."),
    h("h2", {}, "What the levels mean"),
    h("ul", { class: "reasons" },
      h("li", {}, levelTag("high"), " means a strong rule matched, such as a request to hide an action from the user or to read a private key."),
      h("li", {}, levelTag("medium"), " means a weaker rule matched, or the classifier flagged text that the rules scored lower."),
    ),
    p("A flag is a reason to read the text closely. Many flagged tools are security demos, test fixtures or harmless sentences that happen to match a pattern, and no flag claims that anyone acted in bad faith."),
    h("h2", {}, "Disputes"),
    p("Server authors can dispute any flag from its page. The flag stays visible with a note while the dispute is open, and a person then confirms it or clears it. Cleared flags remain listed for transparency but no longer count toward any totals."),
    h("h2", {}, "Limits"),
    p("The scan covers source code on the default branch, so tools generated at runtime or shipped only in packages can be missed. Servers without a public repository cannot be scanned at all, and some descriptions are built from values that only exist at runtime."),
  );
}

function notFound(main, text) {
  main.append(h("h1", {}, "Nothing to show here"), h("p", {}, text), h("p", {}, h("a", { href: "#/" }, "Go back to the list of flagged tools")));
}

/* Router */

async function route() {
  const [path, query] = location.hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean);
  const main = document.getElementById("main");
  main.replaceChildren();
  const here = parts[0] === "method" ? "/method" : ["servers", "server"].includes(parts[0]) ? "/servers" : "/";
  for (const a of document.querySelectorAll("nav a")) {
    if (a.getAttribute("href") === `#${here}`) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  try {
    if (parts[0] === "servers") await viewServers(main, new URLSearchParams(query));
    else if (parts[0] === "server") await viewServer(main, decodeURIComponent(parts.slice(1).join("/")));
    else if (parts[0] === "flag") await viewFlag(main, parts[1]);
    else if (parts[0] === "method") viewMethod(main);
    else await viewHome(main);
  } catch (err) {
    main.replaceChildren(h("h1", {}, "The data did not load"), h("p", {}, `${err.message} Reload the page to try again.`));
  }
  if (parts.length) main.focus({ preventScroll: true });
  window.scrollTo(0, 0);
  const title = main.querySelector("h1")?.textContent;
  document.title = parts.length && title ? `${title} | MCP Sentinel` : "MCP Sentinel";
}

window.addEventListener("hashchange", route);
document.addEventListener("keydown", (e) => {
  const field = document.querySelector(".field input");
  if (e.key !== "/" || !field || e.metaKey || e.ctrlKey || e.target.matches?.("input:not([type=radio]):not([type=checkbox]), select, textarea")) return;
  e.preventDefault();
  field.focus();
});
route();
load("summary").then((s) => {
  document.getElementById("updated").textContent = `Data from the run on ${day(s.generated_at)}, refreshed every morning.`;
}).catch(() => {});
