/* Parts 2-4 of the one-page site (settings, talk alike, late night) and the government timeline
   at the top. Each part is drawn when its figures are on the page. Figures are drawn from data/results/settings.json
   (tools/analyze_settings.py), data/results/similarity.json (tools/analyze_similarity.py)
   and data/results/label_checks.json (tools/check_labels.py). Nothing is computed here
   beyond sorting and formatting. */
(function () {
  "use strict";

  const C = { blue: "#1f5a8c", red: "#b8202e", grey: "#8c8279", ink: "#1f2a33", soft: "#4a5560", grid: "rgba(31,42,51,.12)", paper: "#ffffff" };
  const tooltip = document.getElementById("tooltip");

  /* ---------- helpers ---------- */
  const signed = (v, d = 2) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d);
  const fmt = (v) => Number(v).toLocaleString("en-GB");
  const setN = (key, value) => document.querySelectorAll(`[data-n="${key}"]`).forEach((el) => { el.textContent = value; });

  function showTip(event, title, lines) {
    tooltip.replaceChildren();
    const head = document.createElement("strong");
    head.textContent = title;
    tooltip.append(head);
    lines.forEach((line) => { const d = document.createElement("div"); d.textContent = line; tooltip.append(d); });
    tooltip.hidden = false;
    moveTip(event);
  }
  function moveTip(event) {
    const pad = 14, box = tooltip.getBoundingClientRect();
    let x = event.clientX + pad, y = event.clientY + pad;
    if (x + box.width > window.innerWidth - 8) x = event.clientX - box.width - pad;
    if (y + box.height > window.innerHeight - 8) y = event.clientY - box.height - pad;
    tooltip.style.left = `${Math.max(8, x)}px`;
    tooltip.style.top = `${Math.max(8, y)}px`;
  }
  const hideTip = () => { tooltip.hidden = true; };

  function legend(id, items) {
    const el = document.getElementById(id);
    if (!el) return;
    el.replaceChildren(...items.map((it) => {
      const span = document.createElement("span");
      const mark = document.createElement("i");
      if (it.shape === "line") { mark.className = "line"; mark.style.background = it.color; if (it.dash) mark.style.background = `repeating-linear-gradient(90deg, ${it.color} 0 4px, transparent 4px 7px)`; }
      else if (it.shape === "hollow") { mark.style.border = `2px solid ${it.color}`; mark.style.background = "transparent"; }
      else if (it.shape === "band") { mark.className = "ramp"; mark.style.width = "22px"; mark.style.background = it.color; }
      else mark.style.background = it.color;
      span.append(mark, document.createTextNode(it.label));
      return span;
    }));
  }

  function makeTable(el, headers, rows, numeric = []) {
    if (!el) return;
    const table = document.createElement("table");
    table.className = "data";
    const head = table.createTHead().insertRow();
    headers.forEach((h, i) => { const th = document.createElement("th"); th.textContent = h; if (numeric.includes(i)) th.className = "num"; head.append(th); });
    const body = table.createTBody();
    rows.forEach((r) => {
      const tr = body.insertRow();
      r.forEach((v, i) => { const td = tr.insertCell(); td.textContent = v ?? "–"; if (numeric.includes(i)) td.className = "num"; });
    });
    el.replaceChildren(table);
  }

  function svgIn(id, width, height) {
    const box = d3.select("#" + id);
    box.selectAll("*").remove();
    return box.append("svg").attr("viewBox", `0 0 ${width} ${height}`).attr("role", "img");
  }

  /* A horizontal dot-and-interval chart: rows {label, value, low, high, clear, color, tip}. */
  function dotInterval(id, rows, opts) {
    const width = 760, rowH = 30, left = opts.left || 240, right = 30, top = 34;
    const height = top + rows.length * rowH + 34;
    const svg = svgIn(id, width, height);
    const ext = d3.extent(rows.flatMap((r) => [r.low ?? r.value, r.high ?? r.value, 0]));
    const padX = (ext[1] - ext[0]) * 0.08 || 0.1;
    const x = d3.scaleLinear().domain([ext[0] - padX, ext[1] + padX]).range([left, width - right]).nice();
    const y = (i) => top + i * rowH + rowH / 2;
    svg.append("g").attr("transform", `translate(0,${top - 6})`).call(d3.axisTop(x).ticks(6).tickSize(-(rows.length * rowH + 6)).tickFormat((v) => signed(v, 1)))
      .call((g) => g.select(".domain").remove());
    svg.append("line").attr("x1", x(0)).attr("x2", x(0)).attr("y1", top - 6).attr("y2", top + rows.length * rowH).attr("stroke", C.ink).attr("stroke-width", 1.2);
    if (opts.leftNote) svg.append("text").attr("x", x(0) - 6).attr("y", height - 10).attr("text-anchor", "end").text(opts.leftNote);
    if (opts.rightNote) svg.append("text").attr("x", x(0) + 6).attr("y", height - 10).text(opts.rightNote);
    rows.forEach((r, i) => {
      const g = svg.append("g").attr("tabindex", 0).attr("role", "img").attr("aria-label", `${r.label}: ${signed(r.value)}`);
      svg.append("text").attr("x", left - 10).attr("y", y(i) + 4).attr("text-anchor", "end").attr("class", r.strong ? "strong" : null).text(r.label);
      if (r.low != null) g.append("line").attr("x1", x(r.low)).attr("x2", x(r.high)).attr("y1", y(i)).attr("y2", y(i)).attr("stroke", r.color).attr("stroke-width", 2).attr("stroke-linecap", "round");
      g.append("circle").attr("cx", x(r.value)).attr("cy", y(i)).attr("r", 5.5)
        .attr("fill", r.clear ? r.color : C.paper).attr("stroke", r.clear ? C.paper : r.color).attr("stroke-width", 2);
      g.append("rect").attr("x", left).attr("y", y(i) - rowH / 2).attr("width", width - left - right).attr("height", rowH).attr("fill", "transparent")
        .on("pointermove", (e) => showTip(e, r.label, r.tip)).on("pointerleave", hideTip)
        .on("focus", function () { const b = this.getBoundingClientRect(); showTip({ clientX: b.left + b.width / 2, clientY: b.top }, r.label, r.tip); }).on("blur", hideTip);
    });
  }

  function loadJSON(path) {
    return fetch(path).then((r) => { if (!r.ok) throw new Error(`${path}: ${r.status}`); return r.json(); });
  }
  function fail(error, ...ids) {
    ids.map((id) => document.getElementById(id)).filter(Boolean).forEach((el) => { el.innerHTML = `<p class="wlf-muted">Could not load the data (${error.message}). Serve the repo folder with <code>python -m http.server</code>.</p>`; });
    console.error(error);
  }

  /* ---------- government timeline (top of the page) ---------- */
  function drawGovernments(governments) {
    const parse = d3.utcParse("%Y-%m-%d");
    const end = new Date(Date.UTC(2026, 10, 1));  // the data were collected in November 2026
    const rows = governments.map((g, i) => ({ from: parse(g.from), to: i + 1 < governments.length ? parse(governments[i + 1].from) : end,
      parties: g.parties, counts: g.minister_counts }));
    const width = 960, height = 112, m = { l: 8, r: 8, t: 8, b: 26 };
    const svg = svgIn("fig-governments", width, height);
    const x = d3.scaleUtc().domain([rows[0].from, end]).range([m.l, width - m.r]);
    // One neutral tint for every government: red and blue already mean apart/together in the charts.
    rows.forEach((r) => {
      const x0 = x(r.from), x1 = x(r.to), w = Math.max(1, x1 - x0 - 2);
      const label = r.parties.join(" + ");
      const g = svg.append("g").attr("tabindex", 0).attr("role", "img").attr("aria-label", `${d3.utcFormat("%B %Y")(r.from)}: ${label}`);
      g.append("rect").attr("x", x0 + 1).attr("y", m.t).attr("width", w).attr("height", height - m.t - m.b).attr("rx", 4)
        .attr("fill", C.paper).attr("stroke", "#a8854f").attr("stroke-width", 1);
      if (w > 46) {
        g.append("text").attr("x", x0 + 1 + w / 2).attr("y", m.t + 32).attr("text-anchor", "middle").attr("class", "strong").text(w > 80 ? label : label.replace(/ \+ /g, "+"));
        g.append("text").attr("x", x0 + 1 + w / 2).attr("y", m.t + 52).attr("text-anchor", "middle").text(d3.utcFormat("%Y")(r.from));
      }
      const tip = [`From ${d3.utcFormat("%-d %B %Y")(r.from)}`, `Ministers: ${Object.entries(r.counts).map(([p, n]) => `${p} ${n}`).join(", ")}`];
      g.on("pointermove", (e) => showTip(e, label, tip)).on("pointerleave", hideTip)
        .on("focus", function () { const b = this.getBoundingClientRect(); showTip({ clientX: b.left + b.width / 2, clientY: b.top }, label, tip); })
        .on("blur", hideTip);
    });
    svg.append("g").attr("transform", `translate(0,${height - m.b + 4})`).call(d3.axisBottom(x).ticks(d3.utcYear.every(2)).tickSize(0))
      .call((g) => g.select(".domain").remove());
  }

  /* ---------- tone validation box (settings and late night) ---------- */
  function toneValidation(labels) {
    const el = document.getElementById("tone-validation");
    if (!el) return;
    const s = labels && labels.challenge_stance;
    if (!s || s.status === "not labeled yet" || !s.tone_measures) {
      el.innerHTML = `<span class="wlf-stamp">Validation pending</span> <p>The group has not finished hand-labelling the tone of the 60 sampled short remarks yet, so these tone measures are <strong>not yet checked against human judgement</strong>. Read the results as provisional.</p>`;
      return;
    }
    const names = { afinn_raw: "AFINN, unchanged", afinn_adapted_rate: "AFINN adapted (used here)", model: "Multilingual sentiment model" };
    const rows = Object.entries(s.tone_measures).map(([k, v]) => [names[k] || k, v.spearman ?? "–",
      v.mean_by_label ? (v.mean_by_label.hostile ?? "–") : "–", v.mean_by_label ? (v.mean_by_label.neutral ?? "–") : "–", v.mean_by_label ? (v.mean_by_label.friendly ?? "–") : "–"]);
    el.innerHTML = `<p><strong>Checked against ${s.n} hand-labelled short remarks</strong> (${Object.entries(s.distribution).map(([k, v]) => `${v} ${k}`).join(", ")}). Spearman correlation with the labels (hostile −1, neutral 0, friendly +1), and each measure's mean score within each label. ${typeof s.cohen_kappa === "number" ? `Agreement between two labellers: Cohen's κ = ${s.cohen_kappa}.` : "One labeller so far, so labeller agreement is not yet known."}</p><div class="table-wrap" id="tone-validation-table"></div>`;
    makeTable(document.getElementById("tone-validation-table"), ["Measure", "Spearman", "Mean, hostile", "Mean, neutral", "Mean, friendly"], rows, [1, 2, 3, 4]);
    const used = s.tone_measures.afinn_adapted_rate, raw = s.tone_measures.afinn_raw;
    if (used && used.spearman != null) {
      const strength = Math.abs(used.spearman) < 0.3 ? "weakly" : Math.abs(used.spearman) < 0.5 ? "moderately" : "strongly";
      const reading = document.createElement("p");
      reading.innerHTML = `<strong>What this means:</strong> the measure used on this page agrees ${strength} with human judgement (Spearman ${used.spearman}, p = ${used.p}). Remarks labelled hostile score lower on average (${used.mean_by_label.hostile} against ${used.mean_by_label.neutral} for neutral), but single scores are noisy. Read the results here as differences in <em>word-list tone</em>, which only partly reflect hostility.` +
        (raw && raw.spearman != null && raw.spearman > used.spearman ? ` Dropping the parliament-specific words did not improve agreement (unchanged AFINN: ${raw.spearman}); with 60 labels the two are within noise of each other.` : "");
      el.append(reading);
    }
  }

  /* ---------- Part 2: same member, different setting ---------- */
  const MEASURE_TEXT = {
    tone: { name: "Tone", unit: "AFINN points per 100 words", up: "friendlier", down: "harsher", upColor: C.blue, downColor: C.red },
    negativity: { name: "Negative words", unit: "negative AFINN points per 100 words", up: "more negative words", down: "fewer negative words", upColor: C.red, downColor: C.blue },
    positivity: { name: "Positive words", unit: "positive AFINN points per 100 words", up: "more positive words", down: "fewer positive words", upColor: C.blue, downColor: C.red },
    questions: { name: "Questions", unit: "question marks per 100 words", up: "more questions", down: "fewer questions", upColor: C.ink, downColor: C.ink },
  };

  function settingsPage(S, labels) {
    const tone = S.effects.filter((r) => r.measure === "tone");
    const byLevel = Object.fromEntries(tone.map((r) => [r.level, r]));
    setN("setTurns", fmt(S.corpus.turns_in_settings));
    setN("setMembers", fmt(S.corpus.members));
    setN("reference", S.reference);
    setN("setShuffles", S.shuffles);
    setN("chamBeyond", S.chameleon_summary.beyond_z2);
    setN("chamRanked", S.chameleon_summary.members_ranked);
    setN("chamExpected", S.chameleon_summary.expected_beyond_z2_by_chance);
    setN("qtTone", signed(byLevel["Minister question time"].effect));
    setN("pmTone", signed(byLevel["PM question time"].effect));
    setN("leaderTone", signed(byLevel["Party-leader debate"].effect));
    setN("finalTone", signed(byLevel["Final readings"].effect));
    setN("minCell", S.min_turns_per_cell);
    setN("minCham", S.min_turns_chameleon);
    const dropped = document.getElementById("dropped-words");
    if (dropped) makeTable(dropped, ["Word", "Why it was dropped"], Object.entries(S.dropped_words), []);

    const select = document.getElementById("measure-select");
    select.replaceChildren(...Object.entries(MEASURE_TEXT).map(([k, v]) => new Option(v.name, k)));
    const drawEffects = () => {
      const m = select.value, t = MEASURE_TEXT[m];
      const rows = S.effects.filter((r) => r.measure === m).sort((a, b) => b.effect - a.effect).map((r) => {
        const clear = r.ci_low > 0 || r.ci_high < 0;
        return { label: r.level, value: r.effect, low: r.ci_low, high: r.ci_high, clear, color: r.effect >= 0 ? t.upColor : t.downColor,
          tip: [`${signed(r.effect)} ${t.unit} vs the same members in a routine first reading`, `95% interval over members: ${signed(r.ci_low)} to ${signed(r.ci_high)}`,
            `${r.members} members compared`, `Within-member shuffle: z = ${r.z}`, clear ? "Clear: the interval excludes 0" : "Unclear: the interval includes 0"] };
      });
      rows.push({ label: "Reference: routine bill debate", value: 0, clear: true, color: C.grey, strong: true, tip: ["Every member is compared with themselves in this setting"] });
      dotInterval("fig-settings", rows, { leftNote: `← ${t.down}`, rightNote: `${t.up} →` });
      makeTable(document.getElementById("table-settings"), ["Setting", "Difference", "95% low", "95% high", "Members", "z (shuffle)"],
        S.effects.filter((r) => r.measure === m).map((r) => [r.level, signed(r.effect), signed(r.ci_low), signed(r.ci_high), r.members, r.z]), [1, 2, 3, 4, 5]);
    };
    select.addEventListener("change", drawEffects);
    drawEffects();
    legend("legend-settings", [{ color: C.blue, label: "Friendlier than routine" }, { color: C.red, label: "Harsher than routine" },
      { color: C.ink, shape: "hollow", label: "Hollow: interval includes 0 (unclear)" }]);

    // Figure: government vs opposition members.
    const sideRows = [];
    const gov = Object.fromEntries(S.effects_by_side.government.filter((r) => r.measure === "tone").map((r) => [r.level, r]));
    const opp = Object.fromEntries(S.effects_by_side.opposition.filter((r) => r.measure === "tone").map((r) => [r.level, r]));
    Object.keys(opp).filter((k) => gov[k] && gov[k].members >= 20 && opp[k].members >= 20).sort((a, b) => opp[b].effect - opp[a].effect)
      .forEach((k) => sideRows.push({ level: k, gov: gov[k], opp: opp[k] }));
    drawSides(sideRows);
    makeTable(document.getElementById("table-side"), ["Setting", "Government members", "n", "Opposition members", "n"],
      sideRows.map((r) => [r.level, signed(r.gov.effect), r.gov.members, signed(r.opp.effect), r.opp.members]), [1, 2, 3, 4]);

    drawChameleons(S);
    if (S.second_method) drawMethods(S.second_method);
    else document.getElementById("fig-methods").innerHTML = '<p class="wlf-muted">The second method has not been run yet.</p>';
    makeTable(document.getElementById("table-overview"), ["Setting", "Turns", "Members", "Words", "Tone", "Negative", "Positive", "Questions"],
      S.settings.map((r) => [r.setting, fmt(r.turns), r.members, fmt(r.words), r.tone.toFixed(2), r.negativity.toFixed(2), r.positivity.toFixed(2), r.questions.toFixed(2)]), [1, 2, 3, 4, 5, 6, 7]);
    toneValidation(labels);
  }

  function drawSides(rows) {
    const width = 760, rowH = 34, left = 240, right = 30, top = 34, height = top + rows.length * rowH + 30;
    const svg = svgIn("fig-side", width, height);
    const vals = rows.flatMap((r) => [r.gov.effect, r.opp.effect, 0]);
    const x = d3.scaleLinear().domain(d3.extent(vals)).range([left, width - right]).nice();
    svg.append("g").attr("transform", `translate(0,${top - 6})`).call(d3.axisTop(x).ticks(6).tickSize(-(rows.length * rowH + 6)).tickFormat((v) => signed(v, 1))).call((g) => g.select(".domain").remove());
    svg.append("line").attr("x1", x(0)).attr("x2", x(0)).attr("y1", top - 6).attr("y2", top + rows.length * rowH).attr("stroke", C.ink).attr("stroke-width", 1.2);
    rows.forEach((r, i) => {
      const yy = top + i * rowH + rowH / 2;
      svg.append("text").attr("x", left - 10).attr("y", yy + 4).attr("text-anchor", "end").text(r.level);
      svg.append("line").attr("x1", x(r.gov.effect)).attr("x2", x(r.opp.effect)).attr("y1", yy).attr("y2", yy).attr("stroke", C.grid).attr("stroke-width", 3);
      [["gov", "Government members", true], ["opp", "Opposition members", false]].forEach(([k, label, filled]) => {
        const d = r[k];
        svg.append("circle").attr("cx", x(d.effect)).attr("cy", yy).attr("r", 6).attr("fill", filled ? C.ink : C.paper).attr("stroke", C.ink).attr("stroke-width", 2)
          .attr("tabindex", 0).attr("aria-label", `${r.level}, ${label}: ${signed(d.effect)}`)
          .on("pointermove", (e) => showTip(e, `${r.level}: ${label}`, [`${signed(d.effect)} tone vs the same members in a routine first reading`, `${d.members} members, z = ${d.z}`]))
          .on("pointerleave", hideTip);
      });
      if (i === 0) {
        const lab = (d, t) => svg.append("text").attr("x", x(d.effect)).attr("y", yy - 10).attr("text-anchor", "middle").attr("class", "strong").text(t);
        lab(r.gov, "gov."); lab(r.opp, "opp.");
      }
    });
    svg.append("text").attr("x", x(0) - 6).attr("y", height - 8).attr("text-anchor", "end").text("← harsher");
    svg.append("text").attr("x", x(0) + 6).attr("y", height - 8).text("friendlier →");
    legend("legend-side", [{ color: C.ink, label: "Members of government parties" }, { color: C.ink, shape: "hollow", label: "Members of opposition parties" }]);
  }

  function drawChameleons(S) {
    const all = S.chameleons;
    const harsh = all.slice(0, 8), friendly = all.slice(-8);
    const rows = [...friendly.reverse(), ...harsh.reverse()].sort((a, b) => b.difference - a.difference);
    const width = 760, rowH = 26, top = 30, height = top + rows.length * rowH + 30, mid = 380;
    const svg = svgIn("fig-chameleons", width, height);
    const m = d3.max(rows, (r) => Math.abs(r.difference));
    const x = d3.scaleLinear().domain([-m, m]).range([170, width - 170]).nice();
    svg.append("g").attr("transform", `translate(0,${top - 6})`).call(d3.axisTop(x).ticks(6).tickSize(-(rows.length * rowH + 6)).tickFormat((v) => signed(v, 0))).call((g) => g.select(".domain").remove());
    rows.forEach((r, i) => {
      const yy = top + i * rowH;
      const pos = r.difference >= 0, clear = Math.abs(r.z) >= 2, color = pos ? C.blue : C.red;
      const x0 = x(0), x1 = x(r.difference);
      svg.append("rect").attr("x", Math.min(x0, x1)).attr("y", yy + 4).attr("width", Math.max(1, Math.abs(x1 - x0))).attr("height", rowH - 8).attr("rx", 3)
        .attr("fill", clear ? color : C.paper).attr("stroke", color).attr("stroke-width", clear ? 0 : 1.5)
        .attr("tabindex", 0).attr("aria-label", `${r.name} (${r.party}): ${signed(r.difference)}`)
        .on("pointermove", (e) => showTip(e, `${r.name} (${r.party})`, [`Big debates: tone ${signed(r.flagship_tone)} over ${r.flagship_turns} turns`, `Routine first readings: tone ${signed(r.routine_tone)} over ${r.routine_turns} turns`,
          `Difference ${signed(r.difference)}, z = ${r.z} against shuffling the member's own turns`])).on("pointerleave", hideTip);
      svg.append("text").attr("x", pos ? x0 - 8 : x0 + 8).attr("y", yy + rowH / 2 + 4).attr("text-anchor", pos ? "end" : "start").text(`${r.name} (${r.party})`);
    });
    svg.append("line").attr("x1", x(0)).attr("x2", x(0)).attr("y1", top - 6).attr("y2", top + rows.length * rowH).attr("stroke", C.ink);
    svg.append("text").attr("x", x(0) - 6).attr("y", height - 8).attr("text-anchor", "end").text("← harsher in the big debates");
    svg.append("text").attr("x", x(0) + 6).attr("y", height - 8).text("friendlier in the big debates →");
    legend("legend-chameleons", [{ color: C.blue, label: "Friendlier in big debates" }, { color: C.red, label: "Harsher in big debates" }, { color: C.ink, shape: "hollow", label: "Hollow: |z| < 2" }]);
    makeTable(document.getElementById("table-chameleons"), ["Member", "Party", "Big-debate turns", "Routine turns", "Big-debate tone", "Routine tone", "Difference", "z"],
      [...all].sort((a, b) => Math.abs(b.z) - Math.abs(a.z)).map((r) => [r.name, r.party, r.flagship_turns, r.routine_turns, signed(r.flagship_tone), signed(r.routine_tone), signed(r.difference), r.z]), [2, 3, 4, 5, 6, 7]);
  }

  function drawMethods(M) {
    setN("rhoSettings", M.spearman_setting_means.toFixed(2));
    setN("rhoTurns", M.spearman_turn_level.toFixed(2));
    setN("modelTurns", fmt(M.turns_scored));
    const width = 760, height = 420, m = { l: 70, r: 30, t: 20, b: 50 };
    const svg = svgIn("fig-methods", width, height);
    const x = d3.scaleLinear().domain(d3.extent(M.by_setting, (d) => d.tone)).nice().range([m.l, width - m.r]);
    const y = d3.scaleLinear().domain(d3.extent(M.by_setting, (d) => d.model)).nice().range([height - m.b, m.t]);
    svg.append("g").attr("transform", `translate(0,${height - m.b})`).call(d3.axisBottom(x).ticks(6).tickSize(-(height - m.t - m.b)));
    svg.append("g").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(6).tickSize(-(width - m.l - m.r)));
    svg.append("text").attr("x", (m.l + width - m.r) / 2).attr("y", height - 10).attr("text-anchor", "middle").text("Adapted AFINN tone (mean per setting)");
    svg.append("text").attr("transform", `translate(16,${(height - m.b + m.t) / 2}) rotate(-90)`).attr("text-anchor", "middle").text("Model score, P(pos) − P(neg)");
    M.by_setting.forEach((d) => {
      svg.append("circle").attr("cx", x(d.tone)).attr("cy", y(d.model)).attr("r", 6).attr("fill", C.ink).attr("stroke", C.paper).attr("stroke-width", 2)
        .on("pointermove", (e) => showTip(e, d.setting, [`AFINN tone ${d.tone.toFixed(2)}`, `Model ${d.model.toFixed(3)}`, `${d.turns} sampled turns`])).on("pointerleave", hideTip);
      svg.append("text").attr("x", x(d.tone) + 9).attr("y", y(d.model) + 4).attr("font-size", 11).text(d.setting);
    });
  }

  /* ---------- Part 4: the late-night effect ---------- */
  function lateNightPage(S) {
    const N = S.late_night;
    const bins = N.bins;
    const last = bins[bins.length - 1];
    setN("lateTurns", fmt(last.turns));
    setN("lateMembers", last.members);
    setN("lateTone", signed(last.tone));
    setN("lateZ", signed(last.tone / last.tone_null_sd, 1));
    setN("lateNeg", signed(last.negativity));
    setN("after22", fmt(N.turns_after_22));
    const R = N.after_midnight_robustness;
    if (R) {
      setN("sittings", R.sittings);
      setN("looMin", signed(R.leave_one_sitting_out_min));
      setN("looMax", signed(R.leave_one_sitting_out_max));
      setN("sittingMean", signed(R.sitting_weighted_mean));
      setN("sittingsBelow", R.sittings_below_zero);
    }
    setN("setShuffles", S.shuffles);
    const select = document.getElementById("hour-measure");
    const choices = { tone: "Tone", negativity: "Negative words", positivity: "Positive words", questions: "Questions" };
    select.replaceChildren(...Object.entries(choices).map(([k, v]) => new Option(v, k)));
    const draw = () => {
      const k = select.value;
      const width = 760, height = 380, m = { l: 70, r: 30, t: 24, b: 50 };
      const svg = svgIn("fig-hours", width, height);
      const x = d3.scalePoint().domain(bins.map((b) => b.bin)).range([m.l + 30, width - m.r - 30]);
      const ext = d3.extent(bins.flatMap((b) => [b[k] - 2 * b[k + "_null_sd"], b[k] + 2 * b[k + "_null_sd"], 0]));
      const y = d3.scaleLinear().domain(ext).nice().range([height - m.b, m.t]);
      svg.append("g").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(6).tickSize(-(width - m.l - m.r)).tickFormat((v) => signed(v, 2)));
      svg.append("g").attr("transform", `translate(0,${height - m.b})`).call(d3.axisBottom(x).tickSize(0)).call((g) => g.select(".domain").remove());
      const area = d3.area().x((b) => x(b.bin)).y0((b) => y(-2 * b[k + "_null_sd"])).y1((b) => y(2 * b[k + "_null_sd"]));
      svg.append("path").datum(bins).attr("d", area).attr("fill", C.grey).attr("opacity", 0.22);
      svg.append("line").attr("x1", m.l).attr("x2", width - m.r).attr("y1", y(0)).attr("y2", y(0)).attr("stroke", C.ink).attr("stroke-width", 1.2);
      svg.append("path").datum(bins).attr("d", d3.line().x((b) => x(b.bin)).y((b) => y(b[k]))).attr("fill", "none").attr("stroke", C.ink).attr("stroke-width", 2);
      bins.forEach((b) => {
        const clear = Math.abs(b[k]) > 2 * b[k + "_null_sd"];
        svg.append("circle").attr("cx", x(b.bin)).attr("cy", y(b[k])).attr("r", 6).attr("fill", clear ? C.ink : C.paper).attr("stroke", C.ink).attr("stroke-width", 2)
          .attr("tabindex", 0).attr("aria-label", `${b.bin}: ${signed(b[k], 3)}`)
          .on("pointermove", (e) => showTip(e, b.bin, [`${signed(b[k], 3)} vs the same member in the same kind of debate`, `Shuffle band ±${(2 * b[k + "_null_sd"]).toFixed(3)}`, `${fmt(b.turns)} turns by ${b.members} members`]))
          .on("pointerleave", hideTip);
      });
      svg.append("text").attr("transform", `translate(16,${(height - m.b + m.t) / 2}) rotate(-90)`).attr("text-anchor", "middle").text(`${choices[k]}: difference per 100 words`);
      svg.append("text").attr("x", (m.l + width - m.r) / 2).attr("y", height - 12).attr("text-anchor", "middle").text("Clock time the turn started");
    };
    select.addEventListener("change", draw);
    draw();
    legend("legend-hours", [{ color: C.ink, label: "Observed: filled when outside the band" }, { color: C.grey, shape: "band", label: "Shuffle band: ±2 SD when hours are shuffled within member and kind of debate" }]);
    makeTable(document.getElementById("table-hours"), ["Clock time", "Turns", "Members", "Tone (centred)", "Negative (centred)", "Tone (raw mean)", "Most common settings"],
      bins.map((b) => [b.bin, fmt(b.turns), b.members, signed(b.tone, 3), signed(b.negativity, 3), b.tone_raw.toFixed(2),
        Object.entries(b.top_settings).map(([s, v]) => `${s} ${(v * 100).toFixed(0)}%`).join(", ")]), [1, 2, 3, 4, 5]);
  }

  /* ---------- Part 3: talk alike, fight alike ---------- */
  function languagePage(L) {
    const cross = (m) => L.bins[m].filter((b) => !b.same_party).sort((a, b) => a.bin - b.bin);
    const t = L.tests;
    setN("pairs", fmt(L.cross_party_pairs));
    setN("liftWindow", t.tfidf.exp_window.lift.toFixed(1));
    setN("liftDebate", t.tfidf.exp_debate.lift.toFixed(2));
    setN("liftWindowEmb", t.embedding.exp_window.lift.toFixed(1));
    setN("liftDebateEmb", t.embedding.exp_debate.lift.toFixed(2));
    setN("liftNull", `${t.tfidf.exp_window.null_mean.toFixed(2)} ± ${t.tfidf.exp_window.null_sd.toFixed(2)}`);
    // With n shuffles, no shuffle reaching the observed value means p < 1/n, not p = 0.
    const pText = (p) => (p === 0 ? `p < ${(1 / L.settings.shuffles).toFixed(3)}` : `p = ${p}`);
    setN("pDebate", `${pText(t.tfidf.exp_debate.p_one_sided)} (TF-IDF) and ${pText(t.embedding.exp_debate.p_one_sided)} (embeddings)`);
    setN("simShuffles", L.settings.shuffles);
    setN("agreement", L.method_agreement_spearman.toFixed(2));
    const nmiParty = d3.mean(L.windows, (w) => w.nmi_language_party), nmiChal = d3.mean(L.windows, (w) => w.nmi_language_challenge);
    setN("simNmiParty", nmiParty.toFixed(2));
    setN("simNmiPartyNull", d3.mean(L.windows, (w) => w.nmi_language_party_null).toFixed(2));
    setN("nmiChallenge", nmiChal.toFixed(2));
    setN("nmiChallengeNull", d3.mean(L.windows, (w) => w.nmi_language_challenge_null).toFixed(2));
    setN("simStability", `${d3.min(L.windows, (w) => w.language_stability_nmi).toFixed(2)}–${d3.max(L.windows, (w) => w.language_stability_nmi).toFixed(2)}`);
    setN("minWords", fmt(L.settings.min_words_member));
    setN("k", L.settings.k_neighbours);

    const select = document.getElementById("method-select");
    select.replaceChildren(new Option("TF-IDF (words)", "tfidf"), new Option("Sentence embeddings", "embedding"));
    const draw = () => {
      const rows = cross(select.value);
      const width = 760, height = 380, m = { l: 70, r: 150, t: 20, b: 56 };
      const svg = svgIn("fig-lift", width, height);
      const x = d3.scalePoint().domain(rows.map((r) => r.bin)).range([m.l + 20, width - m.r - 20]);
      const vals = rows.flatMap((r) => [r.ratio_window, r.ratio_debate]);
      const y = d3.scaleLog().domain([Math.min(0.15, d3.min(vals) * 0.8), Math.max(2.5, d3.max(vals) * 1.2)]).range([height - m.b, m.t]);
      svg.append("g").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).tickValues([0.2, 0.5, 1, 2]).tickFormat((v) => `×${v}`).tickSize(-(width - m.l - m.r)));
      svg.append("g").attr("transform", `translate(0,${height - m.b})`).call(d3.axisBottom(x).tickSize(0).tickFormat((b) => ["least alike", "2nd", "3rd", "4th", "most alike"][b])).call((g) => g.select(".domain").remove());
      svg.append("line").attr("x1", m.l).attr("x2", width - m.r).attr("y1", y(1)).attr("y2", y(1)).attr("stroke", C.ink).attr("stroke-width", 1.2);
      [["ratio_window", "vs activity", false], ["ratio_debate", "vs same debate", true]].forEach(([k, label, dash]) => {
        svg.append("path").datum(rows).attr("d", d3.line().x((r) => x(r.bin)).y((r) => y(r[k]))).attr("fill", "none").attr("stroke", C.ink).attr("stroke-width", 2).attr("stroke-dasharray", dash ? "6 4" : null);
        rows.forEach((r) => svg.append("circle").attr("cx", x(r.bin)).attr("cy", y(r[k])).attr("r", 5.5).attr("fill", dash ? C.paper : C.ink).attr("stroke", C.ink).attr("stroke-width", 2)
          .on("pointermove", (e) => showTip(e, `Similarity fifth ${r.bin + 1} of 5`, [`${label}: ×${r[k]}`, `${fmt(r.pairs)} cross-party pairs, ${fmt(r.observed)} challenges`, `Mean similarity ${r.mean_similarity}`])).on("pointerleave", hideTip));
        const lastRow = rows[rows.length - 1];
        svg.append("text").attr("x", x(lastRow.bin) + 12).attr("y", y(lastRow[k]) + 4).attr("class", "strong").text(label);
      });
      svg.append("text").attr("x", m.l + 4).attr("y", y(1) + 16).text("as expected");
      svg.append("text").attr("transform", `translate(16,${(height - m.b + m.t) / 2}) rotate(-90)`).attr("text-anchor", "middle").text("Challenges ÷ expected (log scale)");
      svg.append("text").attr("x", (m.l + width - m.r) / 2).attr("y", height - 12).attr("text-anchor", "middle").text("Pairs of members from different parties, by how alike they talk");
      makeTable(document.getElementById("table-lift"), ["Fifth", "Pairs", "Challenges", "× vs activity", "× vs same debate", "Mean similarity"],
        rows.map((r) => [r.bin + 1, fmt(r.pairs), fmt(r.observed), r.ratio_window, r.ratio_debate, r.mean_similarity]), [1, 2, 3, 4, 5]);
    };
    select.addEventListener("change", draw);
    draw();
    legend("legend-lift", [{ color: C.ink, label: "Against activity alone (how much each member challenges and is challenged)" }, { color: C.ink, shape: "hollow", label: "Against who was in each debate" }]);

    drawNmi(L.windows);
    drawMap(L);
    makeTable(document.getElementById("table-rivals"), ["Government", "Member", "Member", "Challenges", "Expected (activity)", "Expected (same debates)", "Similarity percentile"],
      L.rivals.map((r) => [r.window, `${r.a} (${r.party_a})`, `${r.b} (${r.party_b})`, r.challenges, r.expected_window, r.expected_debate, `${Math.round(r.similarity_percentile * 100)}%`]), [3, 4, 5, 6]);
  }

  function drawNmi(windows) {
    const width = 760, rowH = 30, left = 140, right = 30, top = 34, height = top + windows.length * rowH + 34;
    const svg = svgIn("fig-nmi", width, height);
    const x = d3.scaleLinear().domain([0, Math.max(0.6, d3.max(windows, (w) => w.nmi_language_challenge) * 1.1)]).range([left, width - right]);
    svg.append("g").attr("transform", `translate(0,${top - 6})`).call(d3.axisTop(x).ticks(6).tickSize(-(windows.length * rowH + 6))).call((g) => g.select(".domain").remove());
    windows.forEach((w, i) => {
      const yy = top + i * rowH + rowH / 2;
      svg.append("text").attr("x", left - 10).attr("y", yy + 4).attr("text-anchor", "end").text(w.window);
      [[w.nmi_language_party_null, w.nmi_language_party, false, "party"], [w.nmi_language_challenge_null, w.nmi_language_challenge, true, "challenge communities"]].forEach(([nul, val, filled, label]) => {
        svg.append("line").attr("x1", x(nul)).attr("x2", x(nul)).attr("y1", yy - 7).attr("y2", yy + 7).attr("stroke", C.grey).attr("stroke-width", 2);
        svg.append("circle").attr("cx", x(val)).attr("cy", yy).attr("r", 6).attr("fill", filled ? C.ink : C.paper).attr("stroke", C.ink).attr("stroke-width", 2)
          .on("pointermove", (e) => showTip(e, `${w.window}: language communities vs ${label}`, [`NMI ${val}`, `Shuffled labels: ${nul}`, `${w.members} members, ${w.language_communities} language communities`])).on("pointerleave", hideTip);
        if (i === 0) svg.append("text").attr("x", x(val)).attr("y", yy - 11).attr("text-anchor", "middle").attr("class", "strong").text(filled ? "vs challenges" : "vs party");
      });
    });
    svg.append("text").attr("x", left).attr("y", height - 8).text("NMI: 0 = unrelated, 1 = identical groupings");
    legend("legend-nmi", [{ color: C.ink, label: "Language communities vs challenge-network communities" }, { color: C.ink, shape: "hollow", label: "Language communities vs party" }, { color: C.grey, shape: "line", label: "Same, with shuffled labels" }]);
    makeTable(document.getElementById("table-nmi"), ["Government", "Members", "Language communities", "Modularity", "Stability (NMI)", "vs party", "shuffled", "vs side", "vs challenges", "shuffled"],
      windows.map((w) => [w.window, w.members, w.language_communities, w.language_modularity, w.language_stability_nmi, w.nmi_language_party, w.nmi_language_party_null, w.nmi_language_side, w.nmi_language_challenge, w.nmi_language_challenge_null]), [1, 2, 3, 4, 5, 6, 7, 8, 9]);
  }

  function drawMap(L) {
    const windowSelect = document.getElementById("map-window");
    const partySelect = document.getElementById("map-party");
    const memberInput = document.getElementById("map-member");
    const names = new Map(L.points.map((p) => [p.person, p.name]));
    const windowNames = [...new Set(L.points.map((p) => p.window))];
    windowSelect.replaceChildren(...windowNames.map((w) => new Option(w, w)));
    windowSelect.value = windowNames[windowNames.length - 1];
    let selected = null;
    const panel = document.getElementById("map-panel");

    function showMember(p) {
      selected = p.person;
      panel.replaceChildren();
      const h = document.createElement("h4"); h.textContent = p.name;
      const sub = document.createElement("div"); sub.className = "wlf-muted"; sub.textContent = `${p.party}, ${p.side}. ${fmt(p.words)} words of backbench speech; made ${p.made} and received ${p.received} challenges from members on this map.`;
      panel.append(h, sub);
      const block = (title, items, fmtItem) => {
        const h5 = document.createElement("h5"); h5.textContent = title;
        const ol = document.createElement("ol");
        items.forEach(([id, v]) => {
          const li = document.createElement("li");
          const b = document.createElement("button"); b.type = "button"; b.textContent = names.get(id) || id;
          const other = L.points.find((q) => q.window === p.window && q.person === id);
          if (other) { b.textContent += ` (${other.party})`; b.addEventListener("click", () => { showMember(other); draw(); }); }
          const s = document.createElement("span"); s.textContent = fmtItem(v);
          li.append(b, s); ol.append(li);
        });
        panel.append(h5, items.length ? ol : document.createTextNode("None on this map."));
      };
      block("Talks most like", p.near, (v) => `cos ${v.toFixed(2)}`);
      block("Challenges most with (both ways)", p.partners, (v) => `${v}`);
    }

    function draw() {
      const w = windowSelect.value;
      const points = L.points.filter((p) => p.window === w);
      const parties = [...new Set(points.map((p) => p.party))].sort();
      const current = partySelect.value;
      partySelect.replaceChildren(new Option("All parties", ""), ...parties.map((p) => new Option(p, p)));
      partySelect.value = parties.includes(current) ? current : "";
      const dl = document.getElementById("map-members");
      dl.replaceChildren(...points.map((p) => { const o = document.createElement("option"); o.value = p.name; return o; }));
      const width = 640, height = 520, pad = 20;
      const svg = svgIn("fig-map", width, height);
      const x = d3.scaleLinear().domain(d3.extent(points, (p) => p.x)).range([pad, width - pad]);
      const y = d3.scaleLinear().domain(d3.extent(points, (p) => p.y)).range([height - pad, pad]);
      const sel = points.find((p) => p.person === selected);
      if (sel) {
        sel.near.forEach(([id]) => { const q = points.find((p) => p.person === id); if (q) svg.append("line").attr("x1", x(sel.x)).attr("y1", y(sel.y)).attr("x2", x(q.x)).attr("y2", y(q.y)).attr("stroke", C.grey).attr("stroke-dasharray", "3 3"); });
        sel.partners.forEach(([id]) => { const q = points.find((p) => p.person === id); if (q) svg.append("line").attr("x1", x(sel.x)).attr("y1", y(sel.y)).attr("x2", x(q.x)).attr("y2", y(q.y)).attr("stroke", C.ink).attr("stroke-width", 1.5); });
      }
      const filter = partySelect.value;
      points.sort((a, b) => (a.party === filter) - (b.party === filter)).forEach((p) => {
        const match = !filter || p.party === filter;
        const r = Math.max(4, Math.min(11, Math.sqrt(p.made + p.received) / 2.2));
        svg.append("circle").attr("cx", x(p.x)).attr("cy", y(p.y)).attr("r", r).attr("class", "node")
          .attr("fill", p.side === "government" ? C.blue : C.red).attr("opacity", match ? 0.9 : 0.12)
          .attr("stroke", p.person === selected ? C.ink : C.paper).attr("stroke-width", p.person === selected ? 3 : 1.5)
          .attr("tabindex", match ? 0 : -1).attr("role", "button").attr("aria-label", `${p.name}, ${p.party}`)
          .on("pointermove", (e) => showTip(e, p.name, [`${p.party}, ${p.side}`, `Made ${p.made}, received ${p.received}`]))
          .on("pointerleave", hideTip)
          .on("click", () => { showMember(p); draw(); })
          .on("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showMember(p); draw(); } });
      });
    }
    windowSelect.addEventListener("change", () => { selected = null; panel.innerHTML = '<p class="wlf-muted">Click a member to see who they talk like and who they challenge.</p>'; draw(); });
    partySelect.addEventListener("change", draw);
    memberInput.addEventListener("change", () => {
      const p = L.points.find((q) => q.window === windowSelect.value && q.name.toLowerCase() === memberInput.value.trim().toLowerCase());
      if (p) { showMember(p); draw(); }
    });
    draw();
    legend("legend-map", [{ color: C.blue, label: "Government party" }, { color: C.red, label: "Outside government" },
      { color: C.ink, shape: "line", label: "Selected: challenge partners" }, { color: C.grey, shape: "line", dash: true, label: "Selected: closest in language" }]);
  }

  /* ---------- start ---------- */
  // Each part is drawn only if its figure is on the page, and a failure in one part does not stop the others.
  const has = (id) => document.getElementById(id) !== null;
  if (has("fig-governments")) loadJSON("data/governments.json").then(drawGovernments).catch((e) => fail(e, "fig-governments"));
  if (has("fig-settings") || has("fig-hours")) {
    const labelsP = loadJSON("data/results/label_checks.json").catch(() => null);
    Promise.all([loadJSON("data/results/settings.json"), labelsP]).then(([S, lab]) => {
      if (has("fig-settings")) settingsPage(S, lab);
      if (has("fig-hours")) lateNightPage(S);
    }).catch((e) => fail(e, "fig-settings", "fig-side", "fig-chameleons", "fig-methods", "fig-hours"));
  }
  if (has("fig-lift")) loadJSON("data/results/similarity.json").then(languagePage).catch((e) => fail(e, "fig-lift", "fig-nmi", "fig-map"));
})();

/* Party key: start minimised on phone-sized screens (same rule as on the main page, in site.js). */
(function () {
  "use strict";
  const box = document.getElementById("party-key-box");
  if (box && window.matchMedia("(max-width: 55.99rem)").matches) box.open = false;
})();

/* Header nav: mark the part being read. A part counts as current once its header has passed
   the top quarter of the window. */
(function () {
  "use strict";
  const links = [...document.querySelectorAll(".site-nav a[href^='#']")];
  const targets = links.map((a) => document.querySelector(a.getAttribute("href"))).filter(Boolean);
  if (!targets.length) return;
  function update() {
    const line = window.innerHeight * 0.25;
    let current = null;
    targets.forEach((t) => { if (t.getBoundingClientRect().top <= line) current = t; });
    links.forEach((a) => {
      if (current && a.getAttribute("href") === "#" + current.id) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });
  }
  window.addEventListener("scroll", update, { passive: true });
  window.addEventListener("resize", update);
  update();
})();

/* Cover drawing: 179 seats in a horseshoe, like the chamber. Decoration only: the seats are
   not coloured by party or by data, so it cannot be read as a result. */
(function () {
  "use strict";
  const host = document.getElementById("cover-art");
  if (!host) return;
  const ns = "http://www.w3.org/2000/svg";
  const W = 560, H = 250, cx = W / 2, cy = H - 18, rows = 8, seats = 179;
  const radii = Array.from({ length: rows }, (_, i) => 80 + i * 20);
  const total = radii.reduce((a, r) => a + r, 0);
  let counts = radii.map((r) => Math.round((seats * r) / total));
  counts[rows - 1] += seats - counts.reduce((a, b) => a + b, 0);  // make the rows add up to 179
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const add = (tag, attrs) => { const el = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v)); svg.append(el); return el; };
  radii.forEach((r, i) => {
    const n = counts[i];
    for (let k = 0; k < n; k++) {
      const a = Math.PI - (Math.PI * (k + 0.5)) / n;  // left to right across the half circle
      add("circle", { cx: (cx + r * Math.cos(a)).toFixed(1), cy: (cy - r * Math.sin(a)).toFixed(1), r: 4.6, fill: i % 2 ? "#a8854f" : "#6b1e28", opacity: i % 2 ? 0.55 : 0.8 });
    }
  });
  // the chair's desk and the speakers' lectern in the middle
  add("rect", { x: cx - 34, y: cy - 34, width: 68, height: 12, rx: 2, fill: "none", stroke: "#3a2b1f", "stroke-width": 1.5 });
  add("rect", { x: cx - 9, y: cy - 16, width: 18, height: 16, rx: 2, fill: "none", stroke: "#3a2b1f", "stroke-width": 1.5 });
  add("line", { x1: 30, y1: cy + 10, x2: W - 30, y2: cy + 10, stroke: "#a8854f", "stroke-width": 1 });
  host.append(svg);
})();
