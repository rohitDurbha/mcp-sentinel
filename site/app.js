"use strict";
// One list, one detail pane. Routes: #/flag/<id>, #/server/<name>, #/about, and #/ for the list.
// Every string from a scanned repository is set as text, never as markup.

const REPO = "https://github.com/rohitDurbha/mcp-sentinel";
const SERVER_RESULTS = 100;
const LEVEL = { high: "High risk signal", medium: "Medium risk signal", low: "Low risk signal", cleared: "Cleared by review" };
const STATUS_SHORT = {
  ok: "No flags", no_supported_source: "No supported code", no_repo: "No repository", unreachable: "Unreachable",
  clone_failed: "Not scanned", extract_failed: "Not scanned", pending: "Pending", stale: "Last good scan",
};
const STATUS_LONG = {
  no_supported_source: "No Python, TypeScript, JavaScript or Go source was found in this repository.",
  no_repo: "The registry lists no source repository for this server, so nothing was scanned.",
  unreachable: "The repository could not be reached during the latest daily run.",
  clone_failed: "The repository could not be downloaded during the latest daily run.",
  extract_failed: "The scanner hit an error on this repository and will retry tomorrow.",
  pending: "This repository is queued and will be scanned in the next daily run.",
  stale: "The repository was unreachable today, so the last good scan is shown.",
};
const DISPUTE = {
  open: "The author disputed this result, and it stays visible until a person reviews it.",
  confirmed: "A person reviewed the dispute and kept this flag in place.",
  cleared: "A person reviewed this result and cleared it, so it no longer counts toward totals.",
};

/* Data */

const loaded = {};
const load = (name) => (loaded[name] ??= fetch(`data/${name}.json`).then((r) => {
  if (!r.ok) throw new Error(`data/${name}.json returned HTTP ${r.status}`);
  return r.json();
}));

async function flags() {
  const list = await load("flags");
  if (!list.ready) {
    const rank = { high: 0, medium: 1, low: 2, cleared: 3 };
    for (const f of list) {
      f.shown = f.dispute?.status === "cleared" ? "cleared" : f.level;
      f.hay = `${f.name} ${repoShort(f.repo_url)} ${f.servers.join(" ")} ${f.description}`.toLowerCase();
    }
    list.sort((a, b) => rank[a.shown] - rank[b.shown] || b.rule_score - a.rule_score
      || (b.model?.score ?? 0) - (a.model?.score ?? 0) || a.name.localeCompare(b.name));
    list.byId = new Map(list.map((f) => [f.id, f]));
    list.ready = true;
  }
  return list;
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

/* DOM */

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
  return el;
}
const num = (n) => Number(n).toLocaleString("en-US");
const compact = (n) => new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
const repoShort = (url) => (url || "").replace(/^https:\/\/github\.com\//, "");
const day = (iso) => new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const icon = (level) => h("span", { class: `lv ${level}`, role: "img", "aria-label": LEVEL[level] || "Not flagged" });
const page = (...kids) => h("article", { class: "page" }, h("a", { class: "back", href: "#/" }, "‹ Back"), ...kids);

// Finding offsets count code points, as Python does, so the text is sliced the same way.
function marked(text, spans) {
  const chars = Array.from(text || "");
  const merged = [];
  for (const [s, e] of [...spans].sort((a, b) => a[0] - b[0])) {
    const last = merged.at(-1);
    if (last && s <= last[1]) last[1] = Math.max(last[1], e);
    else merged.push([s, e]);
  }
  const p = h("p", { class: "text" });
  let at = 0;
  for (const [s, e] of merged) {
    p.append(chars.slice(at, s).join(""), h("mark", {}, chars.slice(s, e).join("")));
    at = e;
  }
  p.append(chars.slice(at).join(""));
  return p;
}
const spans = (f, field) => f.findings.filter((x) => x.field === field).map((x) => [x.start, x.end]);

const flagRow = (f, sub = repoShort(f.repo_url)) => h("a", { class: "row", href: `#/flag/${f.id}` },
  icon(f.shown), h("span", { class: "t" }, f.name), h("span", { class: "s" }, sub));
const serverRow = (s) => h("a", { class: "row", href: `#/server/${encodeURIComponent(s.name)}` },
  h("span", { class: "lv" }), h("span", { class: "t" }, s.name), h("span", { class: "s" }, STATUS_SHORT[s.status] || "Not scanned"));

/* Detail views */

async function viewFlag(id) {
  const f = (await flags()).byId.get(id);
  if (!f) return missing("This flag is not in the latest scan, which usually means the tool text changed.");
  const dispute = `${REPO}/issues/new?${new URLSearchParams({
    template: "dispute.yml", title: `Dispute ${f.name} in ${repoShort(f.repo_url)}`, flag: f.id, tool: `${f.name} at ${f.source_url}`,
  })}`;
  const rules = [...new Map(f.findings.map((x) => [x.rule, x])).values()];
  return page(
    h("span", { class: "chip" }, icon(f.shown), LEVEL[f.shown]),
    h("h1", {}, f.name),
    h("a", { class: "where", href: f.source_url }, `${repoShort(f.repo_url)}/${f.path}:${f.line}`),
    f.dispute && h("p", { class: "note" }, DISPUTE[f.dispute.status], f.dispute.note ? ` ${f.dispute.note}` : "",
      f.dispute.issue ? [" ", h("a", { href: f.dispute.issue }, "Read the discussion.")] : ""),
    f.description ? marked(f.description, spans(f, "description")) : null,
    f.params.filter((p) => p.text).map((p) => h("div", { class: "param" },
      h("div", { class: "name" }, p.name || "input"), marked(p.text, spans(f, `param:${p.name || ""}`)))),
    h("h2", {}, "Why"),
    h("ul", { class: "plain rules" },
      rules.map((x) => h("li", {}, icon(x.severity), h("span", {}, x.message), h("code", {}, x.rule))),
      f.model?.flag && h("li", {}, icon("medium"), h("span", {}, "Flagged by the classifier"), h("code", {}, f.model.score.toFixed(2)))),
    h("h2", {}, f.servers.length > 1 ? `Listed by ${f.servers.length} registry entries` : "Listed by"),
    h("ul", { class: "plain links" }, f.servers.map((n) => h("li", {}, h("a", { href: `#/server/${encodeURIComponent(n)}` }, n)))),
    h("div", { class: "actions" }, h("a", { href: f.source_url }, "View source"), h("a", { href: dispute }, "Dispute this result")),
  );
}

async function viewServer(name) {
  const [data, all] = await Promise.all([servers(), flags()]);
  const s = data.byName.get(name);
  if (!s) return missing("No registry entry by that name appeared in the latest scan.");
  const mine = all.filter((f) => f.servers.includes(name));
  const repo = s.repo && h("a", { class: "where", href: s.subfolder ? `${s.repo}/tree/HEAD/${s.subfolder}` : s.repo },
    repoShort(s.repo) + (s.subfolder ? `/${s.subfolder}` : ""));
  const scanned = s.status === "ok" || s.status === "stale";
  return page(
    mine.length ? h("span", { class: "chip" }, icon(s.level), LEVEL[s.level]) : null,
    h("h1", {}, s.name),
    repo,
    s.description && h("p", { class: "lede text" }, s.description),
    h("h2", {}, scanned ? `${num(s.tools)} tools scanned, ${mine.length} flagged` : "Not scanned"),
    STATUS_LONG[s.status] && h("p", {}, STATUS_LONG[s.status]),
    mine.length ? h("ul", { class: "plain links" }, mine.map((f) => h("li", {}, flagRow(f, `${f.path}:${f.line}`)))) : null,
  );
}

async function viewAbout() {
  const [summary, runs, all] = await Promise.all([load("summary"), load("history"), flags()]);
  const level = (key) => runs.filter((r) => r.flagged_unique).map((r) => ({ x: r.generated_at, y: r.flagged_unique[key] }));
  const stat = (value, label) => h("div", {}, h("dt", {}, label), h("dd", {}, value));
  return page(
    h("h1", {}, "About"),
    h("p", { class: "lede" }, "MCP Sentinel reads the source code of every public server in the official MCP registry each day. It marks the words in tool descriptions that could quietly steer an AI assistant against the person using it."),
    h("dl", { class: "numbers" },
      stat(num(summary.servers), "Registry entries"), stat(num(summary.repos_checked), "Repositories checked"),
      stat(num(summary.tools_unique), "Distinct tools"), stat(num(all.filter((f) => f.shown !== "cleared").length), "Flagged tools"),
      stat(day(summary.generated_at), "Latest run")),
    lineChart("Flagged tools", [
      { name: "High", color: "var(--high)", points: level("high") },
      { name: "Medium", color: "var(--medium)", points: level("medium") },
    ]),
    lineChart("Distinct tools", [{ name: "Tools", color: "var(--link)", points: runs.filter((r) => r.tools_unique).map((r) => ({ x: r.generated_at, y: r.tools_unique })) }]),
    h("h2", {}, "Levels"),
    h("ul", { class: "plain rules" },
      h("li", {}, icon("high"), h("span", {}, "A strong rule matched, such as hiding an action from the user or reading a private key."), ""),
      h("li", {}, icon("medium"), h("span", {}, "A weaker rule matched, or the classifier flagged text that the rules scored lower."), "")),
    h("p", {}, "A flag is a reason to read the text closely, and it never claims bad intent. Many flagged tools are security demos or harmless sentences that happen to match a pattern."),
    h("h2", {}, "Method"),
    h("p", {}, "The scanner reads Python, TypeScript, JavaScript and Go as syntax trees and never runs anything it downloads. Explainable rules catch the patterns that published attacks rely on, and a logistic regression classifier trained only on synthetic attacks adds a second opinion. The ",
      h("a", { href: `${REPO}/blob/main/docs/model_card.md` }, "model card"), " records how it was tested and where it falls short."),
    h("h2", {}, "Disputes"),
    h("p", {}, "Authors can dispute any flag from its page. The flag stays visible with a note until a person confirms it or clears it, and cleared flags stop counting toward totals."),
    h("h2", {}, "Data"),
    h("p", {}, "Everything here comes from four JSON files that anyone can download and reuse, and ",
      h("a", { href: "llms.txt" }, "llms.txt"), " describes them for AI agents."),
    h("ul", { class: "plain links" }, ["flags", "servers", "summary", "history"].map((n) => h("li", {}, h("a", { class: "where", href: `data/${n}.json` }, `data/${n}.json`)))),
    h("p", { style: "margin-top:36px" }, "Built by Rohit Durbha, with all of the code open on ", h("a", { href: REPO }, "GitHub"), "."),
  );
}

function missing(text) {
  return page(h("h1", {}, "Not found"), h("p", {}, text));
}

/* Trend chart. One axis, thin lines with markers, direct labels, hover and a table. */

function lineChart(title, series) {
  const fig = h("figure", { class: "chart" }, h("figcaption", {}, title));
  const xs = [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))].sort();
  if (!xs.length) {
    fig.append(h("p", { class: "waiting" }, "The first point arrives with the next daily run."));
    return fig;
  }
  const plot = h("div", { class: "plot" });
  fig.append(plot);
  if (series.length > 1) {
    fig.append(h("div", { class: "legend" }, series.map((s) => h("span", {}, h("span", { class: "key", style: `background:${s.color}` }), s.name))));
  }
  const ns = "http://www.w3.org/2000/svg";
  const svgEl = (tag, attrs, text) => {
    const el = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    if (text != null) el.textContent = text;
    return el;
  };
  const draw = () => {
    const W = Math.max(plot.clientWidth, 260), H = 180, L = 44, R = series.length > 1 ? 64 : 12, T = 10, B = 26;
    const maxY = Math.max(1, ...series.flatMap((s) => s.points.map((p) => p.y)));
    const ts = xs.map((x) => Date.parse(x)), t0 = Math.min(...ts), t1 = Math.max(...ts);
    const X = (x) => (t1 === t0 ? (L + W - R) / 2 : L + ((Date.parse(x) - t0) / (t1 - t0)) * (W - L - R));
    const Y = (y) => T + (1 - y / maxY) * (H - T - B);
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": title });
    for (const v of [0, maxY / 2, maxY]) {
      svg.append(svgEl("line", { class: "grid", x1: L, x2: W - R, y1: Y(v), y2: Y(v) }));
      svg.append(svgEl("text", { x: L - 8, y: Y(v) + 4, "text-anchor": "end" }, compact(v)));
    }
    const ends = new Set([day(xs[0]), day(xs.at(-1))]).size > 1 ? [xs[0], xs.at(-1)] : [xs[0]];
    for (const x of ends) svg.append(svgEl("text", { x: X(x), y: H - 6, "text-anchor": "middle" }, day(x)));
    for (const s of series) {
      if (s.points.length > 1) svg.append(svgEl("polyline", { points: s.points.map((p) => `${X(p.x)},${Y(p.y)}`).join(" "), fill: "none", stroke: s.color, "stroke-width": 2 }));
      for (const p of s.points) svg.append(svgEl("circle", { cx: X(p.x), cy: Y(p.y), r: 4, fill: s.color, stroke: "var(--pane)", "stroke-width": 2 }));
      const last = s.points.at(-1);
      if (series.length > 1 && last) svg.append(svgEl("text", { class: "label", x: X(last.x) + 10, y: Y(last.y) + 4 }, s.name));
    }
    const cross = svgEl("line", { class: "cross", y1: T, y2: H - B, visibility: "hidden" });
    const tip = h("div", { class: "tip", hidden: true });
    svg.append(cross);
    svg.addEventListener("pointermove", (e) => {
      const box = svg.getBoundingClientRect(), px = ((e.clientX - box.left) / box.width) * W;
      const x = xs.reduce((a, b) => (Math.abs(X(b) - px) < Math.abs(X(a) - px) ? b : a));
      for (const k of ["x1", "x2"]) cross.setAttribute(k, X(x));
      cross.setAttribute("visibility", "visible");
      tip.replaceChildren(h("b", {}, day(x)), ...series.map((s) => h("div", {}, `${s.name} ${num(s.points.find((p) => p.x === x)?.y ?? 0)}`)));
      const share = X(x) / W;
      Object.assign(tip.style, { left: `${share * 100}%`, top: `${T + 8}px`, transform: `translateX(${share > 0.6 ? "calc(-100% - 10px)" : share < 0.4 ? "10px" : "-50%"})` });
      tip.hidden = false;
    });
    svg.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; });
    plot.replaceChildren(svg, tip);
  };
  new ResizeObserver(draw).observe(plot);
  fig.append(h("details", {}, h("summary", {}, "Table"), h("table", {},
    h("tr", {}, h("th", {}, "Run"), series.map((s) => h("th", {}, s.name))),
    xs.map((x) => h("tr", {}, h("td", {}, `${x.slice(0, 16).replace("T", " ")} UTC`),
      series.map((s) => h("td", {}, num(s.points.find((p) => p.x === x)?.y ?? 0))))))));
  return fig;
}

/* List and search */

const $q = document.getElementById("q");
const $list = document.getElementById("list");
const $detail = document.getElementById("detail");
let searchToken = 0;

async function renderList() {
  const token = ++searchToken;
  const needle = $q.value.trim().toLowerCase();
  const all = await flags();
  const hits = needle ? all.filter((f) => f.hay.includes(needle)) : all;
  let others = [];
  if (needle.length >= 2) {
    const data = await servers();
    others = data.list.filter((s) => !s.flags && s.hay.includes(needle));
  }
  if (token !== searchToken) return;  // a newer keystroke already rendered
  const items = hits.map((f) => h("li", {}, flagRow(f)));
  if (others.length) {
    if (hits.length) items.unshift(h("li", { class: "group" }, "Flagged tools"));
    items.push(h("li", { class: "group" }, others.length > SERVER_RESULTS ? `Servers, first ${SERVER_RESULTS} of ${num(others.length)}` : "Servers"));
    items.push(...others.slice(0, SERVER_RESULTS).map((s) => h("li", {}, serverRow(s))));
  }
  $list.replaceChildren(...(items.length ? items : [h("li", { class: "none" }, "No matches")]));
  markSelected();
}

function markSelected() {
  const want = location.hash || (wide.matches ? defaultHash : "");
  for (const a of $list.querySelectorAll("a.row")) {
    if (a.getAttribute("href") === want) {
      a.setAttribute("aria-current", "page");
      a.scrollIntoView({ block: "nearest" });
    } else a.removeAttribute("aria-current");
  }
}

/* Router */

const wide = matchMedia("(min-width: 861px)");
let defaultHash = "";
let listScroll = 0;

async function route() {
  const [path, query] = location.hash.slice(1).split("?");
  const parts = path.split("/").filter(Boolean);
  // Earlier versions of the site used these addresses, and shared links should keep working.
  if (parts[0] === "servers") {
    $q.value = new URLSearchParams(query).get("q") || "";
    history.replaceState(null, "", "#/");
    renderList();
    return route();
  }
  if (parts[0] === "method") return location.replace("#/about");

  let view;
  try {
    if (parts[0] === "flag") view = await viewFlag(parts[1]);
    else if (parts[0] === "server") view = await viewServer(decodeURIComponent(parts.slice(1).join("/")));
    else if (parts[0] === "about") view = await viewAbout();
    else {
      const first = (await flags())[0];
      defaultHash = first ? `#/flag/${first.id}` : "";
      view = wide.matches && first ? await viewFlag(first.id) : null;
    }
  } catch (err) {
    view = page(h("h1", {}, "The data did not load"), h("p", {}, `${err.message}, so reload the page to try again.`));
  }
  const toDetail = parts.length > 0;
  if (toDetail && document.body.dataset.view === "list") listScroll = scrollY;
  document.body.dataset.view = toDetail ? "detail" : "list";
  $detail.replaceChildren(view || "");
  $detail.scrollTop = 0;
  if (!wide.matches) scrollTo(0, toDetail ? 0 : listScroll);
  document.title = toDetail && view?.querySelector("h1") ? `${view.querySelector("h1").textContent} | MCP Sentinel` : "MCP Sentinel";
  markSelected();
}

/* Keyboard. Slash searches, arrows walk the list, Escape clears the search or goes back. */

document.addEventListener("keydown", (e) => {
  const typing = e.target === $q;
  if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey) {
    e.preventDefault();
    $q.focus();
    $q.select();
  } else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && (typing || e.target.closest?.("#list"))) {
    const rows = [...$list.querySelectorAll("a.row")];
    if (!rows.length) return;
    e.preventDefault();
    const at = rows.findIndex((a) => a.hasAttribute("aria-current"));
    const next = rows[Math.max(0, Math.min(rows.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)))];
    history.replaceState(null, "", next.getAttribute("href"));
    route();
  } else if (e.key === "Escape") {
    if (typing && $q.value) {
      $q.value = "";
      renderList();
    } else if (!wide.matches && document.body.dataset.view === "detail") location.hash = "#/";
  }
});

$q.addEventListener("input", renderList);
addEventListener("hashchange", route);
wide.addEventListener("change", route);
renderList().catch(() => {});
route();
