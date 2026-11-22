/* Crossing the Aisle: draws every figure from data/site.json, which tools/export_site.py
   writes. The page computes display values only; no result is calculated here. */
(function () {
  "use strict";

  const COLOR = { together: "#0e6aa8", apart: "#b1352a", placebo: "#7d7263", ink: "#2b2622", grid: "rgba(43,38,34,.14)", neutral: "#d8ccb0" };
  const LAYER_NAMES = { votes: "Votes (agreement on contested votes)", challenges: "Floor challenges", same_debate_similarity: "Language: same-debate similarity", party_classifier: "Language: party classifier" };
  // Sign that makes "closer" point right in Figure 2.
  const CLOSER = { votes: 1, challenges: -1, same_debate_similarity: 1, party_classifier: -1 };
  const EVENTS = [
    ["S-V 2022-12-15", "S and V join, December 2022"],
    ["LA-V 2016-11-28", "LA and V join, November 2016"],
    ["RV-S 2011-10-03", "RV and S join, October 2011"],
    ["S-SF 2014-02-03", "S and SF split, February 2014"],
    ["RV-S 2015-06-28", "RV and S split, June 2015"],
    ["LA-V 2019-06-27", "LA and V split, June 2019"],
  ];
  const tooltip = document.getElementById("tooltip");
  let D;

  /* ---------- helpers ---------- */
  const pct = (v, digits = 0) => (v * 100).toFixed(digits) + "%";
  const fmt = (v) => Number(v).toLocaleString("en-GB");
  const pText = (p) => (p < 0.0001 ? "p < 0.0001" : "p = " + (p < 0.01 ? p.toFixed(4) : p.toFixed(2)));
  const relationClass = (r) => (r === "split" ? "apart" : r === "joined" || r === "both_entered" ? "together" : "placebo");

  function setNumber(key, value) {
    document.querySelectorAll(`[data-n="${key}"]`).forEach((el) => { el.textContent = value; });
  }

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
    const box = tooltip.getBoundingClientRect();
    const x = event.clientX ?? event.target.getBoundingClientRect().left;
    const y = event.clientY ?? event.target.getBoundingClientRect().top;
    tooltip.style.left = Math.max(6, Math.min(window.innerWidth - box.width - 6, x + 14)) + "px";
    tooltip.style.top = Math.max(6, y - box.height - 10) + "px";
  }
  const hideTip = () => { tooltip.hidden = true; };

  function makeTable(container, headers, rows, numeric = []) {
    const table = document.createElement("table");
    table.className = "data";
    const head = table.createTHead().insertRow();
    headers.forEach((h, i) => {
      const th = document.createElement("th");
      th.textContent = h;
      if (numeric.includes(i)) th.className = "num";
      head.append(th);
    });
    const body = table.createTBody();
    rows.forEach((row) => {
      const tr = body.insertRow();
      row.forEach((value, i) => {
        const td = tr.insertCell();
        td.textContent = value === null || value === undefined ? "–" : value;
        if (numeric.includes(i)) td.className = "num";
      });
    });
    container.replaceChildren(table);
    return table;
  }

  function legend(id, items) {
    const el = document.getElementById(id);
    el.replaceChildren();
    items.forEach(({ color, label, line, ramp }) => {
      const span = document.createElement("span");
      const mark = document.createElement("i");
      if (line) mark.className = "line";
      if (ramp) { mark.className = "ramp"; mark.style.background = ramp; } else mark.style.background = color;
      span.append(mark, document.createTextNode(label));
      el.append(span);
    });
  }

  function svgFor(id, height, margin) {
    const host = document.getElementById(id);
    host.replaceChildren();
    const width = Math.max(host.clientWidth, 280);
    const svg = d3.select(host).append("svg").attr("viewBox", `0 0 ${width} ${height}`).attr("role", "img");
    return { svg, width, height, inner: { left: margin.left, right: width - margin.right, top: margin.top, bottom: height - margin.bottom } };
  }

  /* ---------- headline numbers ---------- */
  function fillNumbers() {
    const layers = D.layers;
    const challenge = layers.challenges;
    // The headline is about parties entering government together, so only those pairs count here.
    const entering = challenge.rows.filter((r) => relationClass(r.relation) === "together");
    setNumber("foldChange", Math.round(Math.exp(d3.median(entering, (r) => Math.abs(r.change)))) + "-fold");
    setNumber("challengePairs", `${challenge.summary.right_direction} of ${challenge.summary.pairs_tested}`);
    const sv = (D.transitionsSV);
    setNumber("svBefore", fmt(sv.observed_before));
    setNumber("svBeforeExpected", fmt(Math.round(sv.expected_before)));
    setNumber("svAfter", fmt(sv.observed_after));
    setNumber("svAfterExpected", fmt(Math.round(sv.expected_after)));

    const rebels = D.votes.rebels.filter((r) => r.window === "2019 S" || r.window === "2022 M+S+V");
    const rate = d3.sum(rebels, (r) => r.rebel_votes) / d3.sum(rebels, (r) => r.cast);
    setNumber("rebelRate", pct(rate, 2));
    setNumber("rebelWindow", "2019–26");
    setNumber("edges", fmt(D.dataset.usable_edges));
    const people = new Set();
    Object.values(D.networks).forEach((n) => n.nodes.forEach((m) => people.add(m.id)));
    setNumber("members", fmt(people.size));
    setNumber("formations", Object.keys(challenge.summary.by_formation).length);

    const rc = D.validation.recounts;
    setNumber("recount", `${rc.s_v_challenges.raw_xml.before} and ${rc.s_v_challenges.raw_xml.after} from raw XML, against ${rc.s_v_challenges.pipeline.before} and ${rc.s_v_challenges.pipeline.after} from the pipeline, for backbench challenges before and after 2022`);
    setNumber("recountVotes", `S and V majorities matched on ${pct(rc.s_v_votes.from_member_votes)} of ${fmt(rc.s_v_votes.votes)} votes`);
    setNumber("permutations", "20,000");
    const variantText = (v) => `${v.right_direction} of ${v.pairs_tested} pairs in the expected direction, ${pText(v.p_one_sided)}`;
    setNumber("backbench", variantText(D.variants.challenges_backbench_only));
    setNumber("panel", variantText(D.variants.challenges_same_members_panel));
    const svSim = layers.same_debate_similarity.rows.find((r) => r.pair === "S-V" && r.transition === "2022-12-15");
    setNumber("svSimilarity", svSim.placebo_units.toFixed(1));
    const cl = layers.party_classifier.summary;
    setNumber("classifierResult", `${cl.right_direction} of ${cl.pairs_tested} pairs in the expected direction, ${pText(cl.p_one_sided)}`);

    setNumber("roleNull", D.within_party.null_sd.toFixed(2));
    setNumber("roleGap", D.within_party.mean_gap.toFixed(1));
    const roleAcc = D.role_classifier.map((r) => r.accuracy);
    setNumber("roleClassifier", `${d3.min(roleAcc).toFixed(2)}–${d3.max(roleAcc).toFixed(2)}`);

    const voteRows = Object.values(D.votes.vote_network);
    setNumber("voteNmi", `${d3.min(voteRows, (r) => r.nmi_with_party).toFixed(2)}–${d3.max(voteRows, (r) => r.nmi_with_party).toFixed(2)}`);
    setNumber("voteNull", `${d3.min(voteRows, (r) => r.null_within_party_shuffle_nmi).toFixed(2)}–${d3.max(voteRows, (r) => r.null_within_party_shuffle_nmi).toFixed(2)}`);
    setNumber("absent", pct(d3.mean(D.votes.rebels.filter((r) => r.window !== "2026 M+RV+S+SF"), (r) => r.absent_share)));
    setNumber("noRows", fmt(D.collection.votes.votes_without_rows));

    const checks = D.validation.checks;
    setNumber("validationPassed", `${checks.filter((c) => c.passed).length} of ${checks.length}`);
    const status = Object.values(D.dataset.status_by_session);
    const total = d3.sum(status, (s) => d3.sum(Object.values(s)));
    const final = d3.sum(status, (s) => s.Typeset || 0);
    setNumber("provisional", pct(1 - final / total, 1));

    labelStatus();
  }

  function labelStatus() {
    const L = D.labels || {};
    const precision = L.challenge_precision || {};
    const pending = ["challenge_precision", "challenge_missed", "name_resolution", "challenge_stance"].filter((k) => !L[k] || L[k].status !== "labeled");
    const banner = document.getElementById("label-banner");
    if (pending.length) {
      banner.hidden = false;
      document.getElementById("label-banner-text").textContent =
        `The group's hand labels are not finished (${pending.length} of 4 sheets outstanding). Until they are, the challenge rule's accuracy and the tone of challenges are unvalidated, and results here are preliminary.`;
    }
    document.getElementById("precision-text").textContent = precision.status === "labeled"
      ? `In our hand-labeled sample, ${precision.yes} of ${precision.n} edges were real challenges to the floor speaker (95% CI ${precision.ci95[0]}–${precision.ci95[1]}).`
      : "Its accuracy against the group's hand labels is still pending.";
  }

  /* ---------- Figure 1 ---------- */
  function drawTimeline() {
    const key = document.getElementById("event-select").value;
    const timeline = D.timelines[key];
    const [pair, date] = key.split(" ");
    const quarters = d3.range(-10, 10);

    // Votes
    const voteFrame = svgFor("fig-timeline-votes", 170, { top: 26, right: 12, bottom: 22, left: 42 });
    const x = d3.scalePoint().domain(quarters).range([voteFrame.inner.left, voteFrame.inner.right]);
    const yV = d3.scaleLinear().domain([0, 1]).range([voteFrame.inner.bottom, voteFrame.inner.top]);
    drawAxes(voteFrame, x, yV, (v) => pct(v), [0, 0.5, 1]);
    voteFrame.svg.append("text").attr("class", "title").attr("x", voteFrame.inner.left).attr("y", 14).text(`${pair.replace("-", " and ")} voted the same way`);
    const votes = timeline.votes.filter((r) => r.votes >= 5);
    voteFrame.svg.append("path").attr("fill", "none").attr("stroke", COLOR.ink).attr("stroke-width", 2)
      .attr("d", d3.line().x((r) => x(r.quarter)).y((r) => yV(r.agreement))(votes));
    voteFrame.svg.selectAll(".dot").data(votes).join("circle").attr("cx", (r) => x(r.quarter)).attr("cy", (r) => yV(r.agreement)).attr("r", 3.5).attr("fill", COLOR.ink);
    eventLine(voteFrame, x);
    hoverLayer(voteFrame, x, quarters, (q) => {
      const r = timeline.votes.find((v) => v.quarter === q);
      return r && r.votes ? [`Quarter ${q > 0 ? "+" : ""}${q}`, [`${pct(r.agreement)} same side`, `${r.votes} votes`]] : null;
    });

    // Challenges
    const frame = svgFor("fig-timeline-challenges", 220, { top: 26, right: 12, bottom: 38, left: 42 });
    const rows = timeline.challenges.filter((r) => r.observed !== null);
    const yMax = d3.max(rows, (r) => Math.max(r.observed, r.expected)) || 1;
    const y = d3.scaleLinear().domain([0, yMax]).nice().range([frame.inner.bottom, frame.inner.top]);
    drawAxes(frame, x, y, d3.format("d"), y.ticks(4));
    frame.svg.append("text").attr("class", "title").attr("x", frame.inner.left).attr("y", 14).text("Challenges between their members");
    const band = Math.min(14, (frame.inner.right - frame.inner.left) / quarters.length - 4);
    frame.svg.selectAll(".bar").data(rows).join("rect").attr("x", (r) => x(r.quarter) - band / 2).attr("width", band)
      .attr("y", (r) => y(r.observed)).attr("height", (r) => frame.inner.bottom - y(r.observed)).attr("rx", 2).attr("fill", COLOR.together);
    frame.svg.selectAll(".exp").data(rows).join("line").attr("x1", (r) => x(r.quarter) - band / 2 - 2).attr("x2", (r) => x(r.quarter) + band / 2 + 2)
      .attr("y1", (r) => y(r.expected)).attr("y2", (r) => y(r.expected)).attr("stroke", COLOR.ink).attr("stroke-width", 2);
    eventLine(frame, x, true);
    frame.svg.append("text").attr("x", (frame.inner.left + frame.inner.right) / 2).attr("y", 216).attr("text-anchor", "middle").text("Quarters from the new government");
    hoverLayer(frame, x, quarters, (q) => {
      const r = timeline.challenges.find((v) => v.quarter === q);
      return r && r.observed !== null ? [`Quarter ${q > 0 ? "+" : ""}${q}`, [`${r.observed} challenges`, `${r.expected} expected by chance`]] : null;
    });
    const host = document.getElementById("fig-timeline-challenges");
    const note = document.createElement("div");
    note.className = "legend";
    [["Observed (bars)", COLOR.together], ["Expected by chance (lines)", COLOR.ink]].forEach(([label, color]) => {
      const span = document.createElement("span"); const i = document.createElement("i"); i.style.background = color;
      if (label.startsWith("Expected")) i.className = "line";
      span.append(i, document.createTextNode(label)); note.append(span);
    });
    host.prepend(note);

    makeTable(document.getElementById("table-timeline"), ["Quarter", "Votes", "Same side", "Challenges", "Expected"],
      quarters.map((q) => {
        const v = timeline.votes.find((r) => r.quarter === q) || {};
        const c = timeline.challenges.find((r) => r.quarter === q) || {};
        return [q, v.votes ?? 0, v.votes ? pct(v.agreement) : null, c.observed, c.expected];
      }), [0, 1, 2, 3, 4]);
    d3.select("#fig-timeline-votes svg").attr("aria-label", `Vote agreement of ${pair} around ${date}`);
    d3.select("#fig-timeline-challenges svg").attr("aria-label", `Challenges between ${pair} around ${date}, against chance`);
  }

  function drawAxes(frame, x, y, yFormat, yTicks) {
    const { svg, inner } = frame;
    svg.append("g").attr("transform", `translate(${inner.left},0)`)
      .call(d3.axisLeft(y).tickValues(yTicks).tickFormat(yFormat).tickSize(-(inner.right - inner.left)))
      .call((g) => g.select(".domain").remove());
    const every = (inner.right - inner.left) < 420 ? 4 : 2;
    svg.append("g").attr("transform", `translate(0,${inner.bottom})`)
      .call(d3.axisBottom(x).tickValues(x.domain().filter((q) => q % every === 0)).tickSize(3)
        .tickFormat((q) => (q > 0 ? "+" + q : q)));
  }

  function eventLine(frame, x, label) {
    // Formation falls at the boundary between quarter -1 and quarter 0.
    const at = (x(-1) + x(0)) / 2;
    frame.svg.append("line").attr("x1", at).attr("x2", at).attr("y1", frame.inner.top - 2).attr("y2", frame.inner.bottom)
      .attr("stroke", COLOR.apart).attr("stroke-width", 1.5).attr("stroke-dasharray", "4 3");
    if (label) frame.svg.append("text").attr("x", at + 5).attr("y", frame.inner.top + 8).attr("class", "strong").text("Government formed");
  }

  function hoverLayer(frame, x, quarters, describe) {
    const step = x.step();
    frame.svg.selectAll(".hit").data(quarters).join("rect").attr("x", (q) => x(q) - step / 2).attr("width", step)
      .attr("y", frame.inner.top).attr("height", frame.inner.bottom - frame.inner.top).attr("fill", "transparent").attr("tabindex", -1)
      .on("pointermove", (event, q) => { const d = describe(q); if (d) showTip(event, d[0], d[1]); else hideTip(); })
      .on("pointerleave", hideTip);
  }

  /* ---------- Figure 2 ---------- */
  function drawLayers() {
    const order = ["challenges", "votes", "same_debate_similarity", "party_classifier"];
    const rowHeight = 92;
    const frame = svgFor("fig-layers", order.length * rowHeight + 46, { top: 8, right: 12, bottom: 38, left: 12 });
    const { svg, inner } = frame;
    const all = order.flatMap((k) => D.layers[k].rows.map((r) => CLOSER[k] * r.placebo_units));
    const limit = Math.min(18, Math.ceil(d3.max(all, Math.abs)));
    const x = d3.scaleLinear().domain([-limit, limit]).range([inner.left, inner.right]).clamp(true);
    svg.append("g").attr("transform", `translate(0,${inner.bottom})`).call(d3.axisBottom(x).ticks(frame.width < 420 ? 5 : 9).tickSize(3));
    svg.append("line").attr("x1", x(0)).attr("x2", x(0)).attr("y1", inner.top).attr("y2", inner.bottom).attr("stroke", COLOR.ink).attr("stroke-width", 1);
    svg.append("text").attr("x", inner.left).attr("y", frame.height - 4).text("← further apart");
    svg.append("text").attr("x", inner.right).attr("y", frame.height - 4).attr("text-anchor", "end").text("closer →");
    svg.append("text").attr("x", x(0)).attr("y", frame.height - 4).attr("text-anchor", "middle").text("placebo units");

    order.forEach((key, i) => {
      const y0 = inner.top + i * rowHeight;
      const layer = D.layers[key];
      const s = layer.summary;
      svg.append("text").attr("class", "title").attr("x", inner.left).attr("y", y0 + 16).text(LAYER_NAMES[key]);
      svg.append("text").attr("x", inner.right).attr("y", y0 + 16).attr("text-anchor", "end").text(`${s.right_direction} of ${s.pairs_tested} · ${pText(s.p_one_sided)}`);
      const rows = [...layer.rows].sort((a, b) => (relationClass(a.relation) === "placebo" ? -1 : 1) - (relationClass(b.relation) === "placebo" ? -1 : 1));
      svg.selectAll(null).data(rows).join("circle")
        .attr("cx", (r) => x(CLOSER[key] * r.placebo_units))
        .attr("cy", (r) => {
          const lane = relationClass(r.relation) === "placebo" ? 58 : relationClass(r.relation) === "together" ? 42 : 42;
          const jitter = (hash(r.pair + r.transition) - 0.5) * (relationClass(r.relation) === "placebo" ? 18 : 16);
          return y0 + lane + jitter;
        })
        .attr("r", (r) => (relationClass(r.relation) === "placebo" ? 2.5 : 5))
        .attr("fill", (r) => COLOR[relationClass(r.relation)])
        .attr("fill-opacity", (r) => (relationClass(r.relation) === "placebo" ? 0.45 : 0.95))
        .attr("stroke", "#e2d5ae").attr("stroke-width", (r) => (relationClass(r.relation) === "placebo" ? 0 : 1.5))
        .style("cursor", "default")
        .on("pointermove", (event, r) => showTip(event, r.pair, [
          `${(CLOSER[key] * r.placebo_units).toFixed(1)} placebo units`, `Raw change ${r.change.toFixed(3)}`,
          `Formation ${r.transition}`, r.relation.replace("_", " "),
        ]))
        .on("pointerleave", hideTip);
    });
    legend("legend-layers", [
      { color: COLOR.together, label: "Entered government together" },
      { color: COLOR.apart, label: "Split up" },
      { color: COLOR.placebo, label: "Relation unchanged (placebo)" },
    ]);
    const rows = order.flatMap((k) => D.layers[k].rows.filter((r) => relationClass(r.relation) !== "placebo").map((r) => [
      LAYER_NAMES[k], r.transition, r.pair, r.relation.replace("_", " "), r.change.toFixed(3), r.placebo_units.toFixed(1),
    ]));
    makeTable(document.getElementById("table-layers"), ["Layer", "Formation", "Pair", "Relation", "Raw change", "Placebo units"], rows, [4, 5]);
  }

  function hash(text) {
    let h = 0;
    for (let i = 0; i < text.length; i += 1) h = (h * 31 + text.charCodeAt(i)) % 9973;
    return h / 9973;
  }

  /* ---------- Figure 3 ---------- */
  function drawRole() {
    const parse = (q) => new Date(+q.slice(0, 4), (+q.slice(5) - 1) * 3 + 1, 15);
    const rows = D.role_rates.map((r) => ({ ...r, date: parse(r.quarter) }));
    const frame = svgFor("fig-role", 310, { top: 54, right: 34, bottom: 28, left: 36 });
    const { svg, inner } = frame;
    const x = d3.scaleTime().domain(d3.extent(rows, (r) => r.date)).range([inner.left, inner.right]);
    const y = d3.scaleLinear().domain([0, d3.max(rows, (r) => r.rate)]).nice().range([inner.bottom, inner.top]);
    svg.append("g").attr("transform", `translate(${inner.left},0)`).call(d3.axisLeft(y).ticks(5).tickSize(-(inner.right - inner.left))).call((g) => g.select(".domain").remove());
    svg.append("g").attr("transform", `translate(0,${inner.bottom})`).call(d3.axisBottom(x).ticks(d3.timeYear.every(frame.width < 480 ? 4 : 2)).tickSize(3));
    const series = [["S", COLOR.apart], ["V", COLOR.together]];
    series.forEach(([party, color], i) => {
      const part = rows.filter((r) => r.party === party).sort((a, b) => a.date - b.date);
      const y0 = 8 + i * 20;
      svg.append("text").attr("x", inner.left - 6).attr("y", y0 + 10).attr("text-anchor", "end").attr("class", "strong").text(party);
      D.windows.filter((w) => w.government.includes(party)).forEach((w) => {
        const a = x(new Date(Math.max(new Date(w.from), x.domain()[0])));
        const b = x(new Date(Math.min(new Date(w.to), x.domain()[1])));
        if (b > a) svg.append("rect").attr("x", a).attr("width", b - a).attr("y", y0).attr("height", 12).attr("rx", 2).attr("fill", color).attr("fill-opacity", 0.85);
      });
      svg.append("path").attr("fill", "none").attr("stroke", color).attr("stroke-width", 2)
        .attr("d", d3.line().x((r) => x(r.date)).y((r) => y(r.rate))(part));
      const last = part[part.length - 1];
      svg.append("text").attr("x", x(last.date) + 5).attr("y", y(last.rate) + 4).attr("class", "strong").text(party);
    });
    const quarters = [...new Set(rows.map((r) => r.quarter))].sort();
    const dates = quarters.map(parse);
    const cross = svg.append("line").attr("y1", inner.top).attr("y2", inner.bottom).attr("stroke", COLOR.ink).attr("stroke-width", 1).attr("opacity", 0);
    svg.append("rect").attr("x", inner.left).attr("width", inner.right - inner.left).attr("y", inner.top).attr("height", inner.bottom - inner.top).attr("fill", "transparent")
      .on("pointermove", (event) => {
        const [mx] = d3.pointer(event);
        const at = x.invert(mx);
        const i = d3.bisectCenter(dates, at);
        const q = quarters[i];
        cross.attr("x1", x(dates[i])).attr("x2", x(dates[i])).attr("opacity", 0.5);
        const lines = series.map(([p]) => {
          const r = rows.find((v) => v.party === p && v.quarter === q);
          return r ? `${p}: ${r.rate} per 1,000 (${r.government ? "in government" : "in opposition"})` : `${p}: too little speech`;
        });
        showTip(event, q, lines);
      })
      .on("pointerleave", () => { cross.attr("opacity", 0); hideTip(); });
    legend("legend-role", [
      { color: COLOR.apart, line: true, label: "S (Socialdemokratiet)" },
      { color: COLOR.together, line: true, label: "V (Venstre)" },
      { color: COLOR.ink, label: "Top bars: party holds ministers" },
    ]);
    const wp = D.within_party.parties.map((p) => [p.party, p.opposition_rate, p.government_rate, p.quarters]);
    const host = document.getElementById("table-role");
    const first = document.createElement("div"); const second = document.createElement("div");
    host.replaceChildren(first, second);
    makeTable(first, ["Tested on", "Accuracy", "Shuffled mean", "Shuffled max"], D.role_classifier.map((r) => [r.window, r.accuracy, r.null_mean, r.null_max]), [1, 2, 3]);
    makeTable(second, ["Party", "Opposition rate", "Government rate", "Quarters"], wp, [1, 2, 3]);
  }

  /* ---------- Figure 4 ---------- */
  function drawMatrix() {
    const name = document.getElementById("matrix-select").value;
    const m = D.mixing[name];
    const n = m.parties.length;
    const host = document.getElementById("fig-matrix");
    const avail = Math.max(host.clientWidth, 280);
    const left = 44; const top = 26;
    const cell = Math.min(50, (avail - left - 4) / n);
    const frame = svgFor("fig-matrix", top + cell * n + 24, { top, right: 4, bottom: 24, left });
    const { svg } = frame;
    const color = d3.scaleDiverging([-2, 0, 2], (t) => (t < 0.5
      ? d3.interpolateRgb(COLOR.together, COLOR.neutral)(t * 2)
      : d3.interpolateRgb(COLOR.neutral, COLOR.apart)((t - 0.5) * 2))).clamp(true);
    const label = (p) => (m.government.includes(p) ? p + "★" : p);
    m.parties.forEach((p, i) => {
      svg.append("text").attr("x", left - 5).attr("y", top + cell * i + cell / 2 + 4).attr("text-anchor", "end").attr("class", m.government.includes(p) ? "strong" : "").text(label(p));
      svg.append("text").attr("x", left + cell * i + cell / 2).attr("y", top - 7).attr("text-anchor", "middle").attr("class", m.government.includes(p) ? "strong" : "").text(label(p));
    });
    svg.append("text").attr("x", left).attr("y", top + cell * n + 18).text("Rows challenge columns");
    m.parties.forEach((a, i) => m.parties.forEach((b, j) => {
      const o = m.observed[i][j]; const e = m.expected[i][j];
      if (e < 5) {
        svg.append("rect").attr("x", left + cell * j + 1).attr("y", top + cell * i + 1).attr("width", cell - 2).attr("height", cell - 2).attr("rx", 2)
          .attr("fill", "none").attr("stroke", COLOR.grid)
          .on("pointermove", (event) => showTip(event, `${a} → ${b}`, [`${o} challenges, ${e} expected`, "Too few to read"])).on("pointerleave", hideTip);
        return;
      }
      const ratio = (o + 0.5) / (e + 0.5);
      svg.append("rect").attr("x", left + cell * j + 1).attr("y", top + cell * i + 1).attr("width", cell - 2).attr("height", cell - 2).attr("rx", 2)
        .attr("fill", color(Math.log2(ratio)))
        .on("pointermove", (event) => showTip(event, `${ratio.toFixed(2)}× chance`, [`${a} → ${b}`, `${o} challenges, ${e} expected`, `z = ${m.z[i][j]}`]))
        .on("pointerleave", hideTip);
      if (cell >= 32) {
        const dark = Math.abs(Math.log2(ratio)) > 1.1;
        svg.append("text").attr("x", left + cell * j + cell / 2).attr("y", top + cell * i + cell / 2 + 4).attr("text-anchor", "middle")
          .style("fill", dark ? "#fff" : COLOR.ink).style("font-size", "11px").style("pointer-events", "none").text(ratio < 10 ? ratio.toFixed(1) : Math.round(ratio));
      }
    }));
    legend("legend-matrix", [{ ramp: `linear-gradient(90deg, ${COLOR.together}, ${COLOR.neutral}, ${COLOR.apart})`, label: "¼× chance · as chance · 4× chance" }]);
    const w = D.per_window[name];
    setNumber("assortParty", w.party_assortativity.observed.toFixed(3));
    setNumber("assortSide", w.side_assortativity.observed.toFixed(3));
    setNumber("assortNull", `${w.party_assortativity.null_mean.toFixed(3)} ± ${w.party_assortativity.null_sd.toFixed(3)} and ${w.side_assortativity.null_mean.toFixed(3)} ± ${w.side_assortativity.null_sd.toFixed(3)}`);
  }

  /* ---------- Figure 5 ---------- */
  let selected = null;

  function drawNetwork() {
    const name = document.getElementById("net-window").value;
    const partyFilter = document.getElementById("net-party").value;
    const net = D.networks[name];
    const nodes = net.nodes.filter((n) => n.x !== null);
    const byId = new Map(net.nodes.map((n) => [n.id, n]));
    const host = document.getElementById("fig-network");
    const width = Math.max(host.clientWidth, 280);
    const height = Math.min(520, Math.max(340, width * 0.9));
    const frame = svgFor("fig-network", height, { top: 6, right: 6, bottom: 6, left: 6 });
    const { svg, inner } = frame;
    const x = d3.scaleLinear().domain(d3.extent(nodes, (n) => n.x)).range([inner.left + 8, inner.right - 8]);
    const y = d3.scaleLinear().domain(d3.extent(nodes, (n) => n.y)).range([inner.top + 8, inner.bottom - 8]);
    const r = d3.scaleSqrt().domain([0, d3.max(nodes, (n) => n.made + n.received)]).range([2.5, 10]);
    const neighbours = new Set();
    if (selected) net.edges.forEach(([a, b]) => { if (a === selected) neighbours.add(b); if (b === selected) neighbours.add(a); });
    const links = svg.append("g");
    net.edges.forEach(([a, b, w]) => {
      const A = byId.get(a); const B = byId.get(b);
      if (A.x === null || B.x === null) return;
      const lit = selected && (a === selected || b === selected);
      links.append("line").attr("x1", x(A.x)).attr("y1", y(A.y)).attr("x2", x(B.x)).attr("y2", y(B.y))
        .attr("stroke", lit ? COLOR.ink : "#7d7263").attr("stroke-opacity", lit ? 0.75 : selected ? 0.08 : 0.22)
        .attr("stroke-width", lit ? Math.min(3, 0.8 + w / 8) : 0.8);
    });
    const group = svg.append("g");
    nodes.forEach((n) => {
      const matches = !partyFilter || n.party === partyFilter;
      const dim = !matches || (selected && n.id !== selected && !neighbours.has(n.id));
      const g = group.append("g").attr("class", "node").attr("transform", `translate(${x(n.x)},${y(n.y)})`).attr("tabindex", matches ? 0 : -1).attr("role", "button").attr("aria-label", `${n.name}, ${n.party}`)
        .on("click", () => selectMember(n.id))
        .on("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectMember(n.id); } })
        .on("pointermove", (event) => showTip(event, n.name, [`${n.party}, ${n.side}`, `Made ${n.made}, received ${n.received}`]))
        .on("pointerleave", hideTip);
      g.append("circle").attr("r", Math.max(r(n.made + n.received), 11)).attr("fill", "transparent");
      g.append("circle").attr("class", "mark").attr("r", r(n.made + n.received)).attr("fill", n.side === "government" ? COLOR.together : COLOR.apart)
        .attr("fill-opacity", dim ? 0.14 : 0.95).attr("stroke", n.id === selected ? COLOR.ink : "#e2d5ae").attr("stroke-width", n.id === selected ? 2.5 : 1);
    });
    if (selected && byId.get(selected) && byId.get(selected).x !== null) {
      const n = byId.get(selected);
      const side = x(n.x) > width * 0.7 ? "end" : "start";
      svg.append("text").attr("x", x(n.x) + (side === "start" ? 12 : -12)).attr("y", y(n.y) + 4).attr("text-anchor", side).attr("class", "strong").style("paint-order", "stroke").style("stroke", "#e2d5ae").style("stroke-width", "3px").text(n.name);
    }
    legend("legend-net", [{ color: COLOR.together, label: "Government party" }, { color: COLOR.apart, label: "Outside government" }, { color: "#7d7263", label: "Size: challenges made and received" }]);
    renderPanel(net, byId);

    const w = D.per_window[name];
    setNumber("backboneEdges", fmt(net.backbone_edges));
    setNumber("membersDrawn", `${fmt(net.members_drawn)} of ${fmt(net.nodes.length)}`);
    setNumber("allEdges", fmt(net.edges_all));
    setNumber("modularity", w.communities.modularity.toFixed(2));
    setNumber("modularityNull", `${w.communities.null_modularity_mean.toFixed(2)} ± ${w.communities.null_modularity_sd.toFixed(3)}`);
    setNumber("stability", w.communities.seed_stability_nmi_mean.toFixed(2));
    setNumber("nmiParty", w.communities.nmi_with_party.toFixed(2));
    setNumber("committeeShare", pct(w.committee_test.share_sharing_a_committee));
    setNumber("committeeNull", pct(w.committee_test.null_mean));
    const rows = Object.entries(w.community_topics).map(([c, t]) => [`Community ${+c + 1}`, t.members, t.words.join(", ")]);
    const table = makeTable(document.getElementById("table-communities"), ["", "Members", "Words setting its debates apart"], rows, [1]);
    table.querySelectorAll("tbody td:nth-child(3)").forEach((td) => td.classList.add("wrap"));
  }

  function selectMember(id) {
    selected = selected === id ? null : id;
    drawNetwork();
  }

  function renderPanel(net, byId) {
    const panel = document.getElementById("member-panel");
    panel.replaceChildren();
    const member = selected ? byId.get(selected) : null;
    if (!member) {
      const p = document.createElement("p");
      p.className = "wlf-muted";
      p.textContent = selected ? "This member did not take part in this period." : "Click a member to see who they challenged most and who challenged them.";
      panel.append(p);
      return;
    }
    const h = document.createElement("h4"); h.textContent = member.name;
    const sub = document.createElement("div"); sub.className = "wlf-muted"; sub.textContent = `${member.party}, ${member.side}. Made ${member.made}, received ${member.received}.`;
    panel.append(h, sub);
    [["Challenged most", member.challenged], ["Challenged most by", member.challenged_by]].forEach(([title, list]) => {
      const head = document.createElement("h5"); head.textContent = title;
      const ol = document.createElement("ol");
      list.forEach(([id, count]) => {
        const other = byId.get(id);
        const li = document.createElement("li");
        const button = document.createElement("button");
        button.textContent = other ? `${other.name} (${other.party})` : String(id);
        button.addEventListener("click", () => { selected = id; drawNetwork(); });
        const n = document.createElement("span"); n.textContent = count;
        li.append(button, n); ol.append(li);
      });
      panel.append(head, ol);
    });
  }

  function fillNetworkControls() {
    const name = document.getElementById("net-window").value;
    const net = D.networks[name];
    const partySelect = document.getElementById("net-party");
    const current = partySelect.value;
    partySelect.replaceChildren(new Option("All parties", ""), ...[...new Set(net.nodes.map((n) => n.party))].sort().map((p) => new Option(p, p)));
    partySelect.value = [...partySelect.options].some((o) => o.value === current) ? current : "";
    const list = document.getElementById("member-list");
    list.replaceChildren(...net.nodes.map((n) => n.name).sort().map((v) => { const o = document.createElement("option"); o.value = v; return o; }));
  }

  /* ---------- static tables ---------- */
  function drawTables() {
    const d = D.dataset; const c = D.collection;
    makeTable(document.getElementById("table-data"), ["What", "How many", "From"], [
      ["Debate files (sittings)", fmt(c.debates.files), "FTP, sessions 2009-10 to 2025-26"],
      ["Speech turns", fmt(d.turns), `of which ${fmt(d.chair_turns)} by the chair`],
      ["Words in backbench speech analysed", fmt(D.language_corpus.words), `${fmt(D.language_corpus.speakers)} speakers`],
      ["Challenges found / usable", `${fmt(d.challenges.edges)} / ${fmt(d.usable_edges)}`, "Rule on the chair's calls"],
      ["Votes with party positions", fmt(d.party_positions.votes_parsed), `${fmt(d.party_positions.votes_unparsed)} older votes have totals only`],
      ["Individual member votes", fmt(c.votes.rows), `${fmt(c.votes.votes)} votes, sessions 2017-18 to 2025-26`],
      ["Party memberships", fmt(c.tables.memberships), `${fmt(c.tables.party_groups)} party groups, per session`],
      ["Committee memberships", fmt(c.committees.memberships), `${fmt(c.committees.committees)} committees, per session`],
    ], [1]);
    const statuses = [...new Set(Object.values(d.status_by_session).flatMap(Object.keys))].sort();
    makeTable(document.getElementById("table-status"), ["Session", ...statuses],
      Object.entries(d.status_by_session).sort().map(([s, v]) => [s, ...statuses.map((k) => fmt(v[k] || 0))]), statuses.map((_, i) => i + 1));
    makeTable(document.getElementById("table-validation"), ["Check", "Result", "Detail"], D.validation.checks.map((x) => [x.check, x.passed ? "Passed" : "FAILED", x.detail]));
  }

  /* ---------- start ---------- */
  function init() {
    const eventSelect = document.getElementById("event-select");
    EVENTS.forEach(([v, l]) => eventSelect.add(new Option(l, v)));
    const windows = D.drawn_windows;
    ["matrix-select", "net-window"].forEach((id) => {
      const s = document.getElementById(id);
      windows.forEach((w) => {
        const row = D.windows.find((x) => x.name === w);
        s.add(new Option(`${row.government.join("+")}, from ${row.from.slice(0, 4)}`, w));
      });
      s.value = "2022 M+S+V";
    });
    fillNumbers(); drawTables();
    fillNetworkControls();
    const drawAll = () => { drawTimeline(); drawLayers(); drawRole(); drawMatrix(); drawNetwork(); };
    eventSelect.addEventListener("change", drawTimeline);
    document.getElementById("matrix-select").addEventListener("change", drawMatrix);
    document.getElementById("net-window").addEventListener("change", () => { fillNetworkControls(); drawNetwork(); });
    document.getElementById("net-party").addEventListener("change", drawNetwork);
    document.getElementById("net-member").addEventListener("change", (e) => {
      const m = D.networks[document.getElementById("net-window").value].nodes.find((n) => n.name === e.target.value);
      if (m) { selected = m.id; drawNetwork(); }
    });
    drawAll();
    let timer;
    let lastWidth = window.innerWidth;
    window.addEventListener("resize", () => {
      if (window.innerWidth === lastWidth) return;
      lastWidth = window.innerWidth;
      clearTimeout(timer);
      timer = setTimeout(drawAll, 200);
    });
  }

  fetch("data/site.json").then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }).then((data) => { D = data; init(); })
    .catch((error) => {
      const p = document.createElement("p");
      p.textContent = `The figures could not load (${error.message}).`;
      document.getElementById("evidence").after(p);
    });
})();

/* Party key: on wide screens keep it open and just below the masthead (it follows the
   page once the masthead scrolls away); on narrow screens start it closed as a button. */
(function () {
  "use strict";
  const box = document.getElementById("party-key-box");
  const masthead = document.querySelector(".wlf-masthead");
  if (!box) return;
  const wide = window.matchMedia("(min-width: 80rem)");
  if (!wide.matches) box.open = false;
  function place() {
    const bottom = masthead ? masthead.getBoundingClientRect().bottom : 0;
    document.documentElement.style.setProperty("--key-top", `${Math.max(16, bottom + 16)}px`);
  }
  place();
  window.addEventListener("scroll", place, { passive: true });
  window.addEventListener("resize", place);
  wide.addEventListener("change", (e) => { box.open = e.matches; });
})();
