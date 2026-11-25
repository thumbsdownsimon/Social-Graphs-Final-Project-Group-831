/* Crossing the Aisle: draws every figure from data/site.json, which tools/export_site.py
   writes. The page computes display values only; no result is calculated here. */
(function () {
  "use strict";

  // Chamber/Nordic theme. together and apart pass the dataviz palette validator on white and ivory.
  const COLOR = { together: "#1f5a8c", apart: "#b8202e", placebo: "#8c8279", ink: "#1f2a33", grid: "rgba(31,42,51,.12)", neutral: "#e7e3da", paper: "#ffffff" };
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
  let X = null;  // data/emoji_examples.json

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
    const stance = L.challenge_stance || {};
    const banner = document.getElementById("label-banner");
    if (precision.status !== "labeled") {
      // State what was and was not checked by hand, rather than a count of unfinished sheets.
      const tone = stance.n
        ? `Tone was checked against ${stance.n} hand-labelled short remarks by one labeller (Part 2).`
        : "Tone has not been checked against hand labels either.";
      banner.hidden = false;
      document.getElementById("label-banner-text").textContent =
        `The rule that finds challenges in the transcripts has not been checked against hand labels, so its error rate is unknown; read the network results with that in mind. ${tone}`;
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
        .attr("stroke", COLOR.paper).attr("stroke-width", (r) => (relationClass(r.relation) === "placebo" ? 0 : 1.5))
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

  /* ---------- Figure 5: one member network per layer (data/layers.json, archetypes/run_layers.py) ---------- */
  let L = null;
  let selected = null;
  const TONE = { hostile: "#c4661f", neutral: "#a39a8c", friendly: "#2f7d4f" };
  const LAYER_UI = {
    C: { title: "The network is organised by policy area, not party", size: "Size: challenges made and received" },
    E: { title: "Committees: who sits on the same committees", size: "Size: lines drawn", lists: [["Shares most committees with", null]] },
  };
  const layerValue = () => document.getElementById("net-layer").value;
  const windowValue = () => document.getElementById("net-window").value;

  // The challenge network from site.json, in the layer format, for when layers.json is missing.
  function siteChallengeNet(name) {
    const n = D.networks[name];
    return { nodes: n.nodes.map((m) => ({ ...m, out: m.challenged, in: m.challenged_by })), edges: n.edges, drawn: n.members_drawn, edges_all: n.edges_all };
  }
  function currentNet(layer, name) {
    if (L) return (L.networks[layer] || {})[name] || null;
    return layer === "C" ? siteChallengeNet(name) : null;
  }
  function toneOf(t) {
    const total = t[0] + t[1] + t[2];
    if (!total) return null;
    const net = (t[2] - t[0]) / total;
    return net <= -0.25 ? "hostile" : net >= 0.25 ? "friendly" : "neutral";
  }

  function showLayerText(layer) {
    document.getElementById("net-title").textContent = LAYER_UI[layer].title;
    const def = L ? L.layers[layer] : null;
    document.getElementById("net-layer-note").textContent = def ? `Line: ${def.edge.toLowerCase()} · Edge property: ${def.property.toLowerCase()}` : "";
    document.querySelectorAll("#explore [data-layer]").forEach((el) => { el.hidden = el.dataset.layer !== layer; });
    document.getElementById("net-tone-label").hidden = !(layer === "C" && L);
  }

  function drawNetwork() {
    const layer = layerValue();
    const name = windowValue();
    const partyFilter = document.getElementById("net-party").value;
    showLayerText(layer);
    const net = currentNet(layer, name);
    const host = document.getElementById("fig-network");
    const stats = document.getElementById("layer-stats");
    if (!net) {
      const p = document.createElement("p");
      p.className = "wlf-muted empty-layer";
      p.textContent = !L ? "The layer data (data/layers.json) could not load, so only the challenge layer is shown."
        : "No data for this layer in this period.";
      host.replaceChildren(p);
      legend("legend-net", []);
      stats.hidden = true;
      renderPanel(layer, null, new Map());
      return;
    }
    const nodes = net.nodes.filter((n) => n.x !== null);
    const byId = new Map(net.nodes.map((n) => [n.id, n]));
    const degree = new Map();
    net.edges.forEach(([a, b]) => { degree.set(a, (degree.get(a) || 0) + 1); degree.set(b, (degree.get(b) || 0) + 1); });
    const sizeOf = layer === "C" ? (n) => n.made + n.received : (n) => degree.get(n.id) || 0;
    const width = Math.max(host.clientWidth, 280);
    const height = Math.min(520, Math.max(340, width * 0.9));
    const frame = svgFor("fig-network", height, { top: 6, right: 6, bottom: 6, left: 6 });
    const { svg, inner } = frame;
    const x = d3.scaleLinear().domain(d3.extent(nodes, (n) => n.x)).range([inner.left + 8, inner.right - 8]);
    const y = d3.scaleLinear().domain(d3.extent(nodes, (n) => n.y)).range([inner.top + 8, inner.bottom - 8]);
    const r = d3.scaleSqrt().domain([0, d3.max(nodes, sizeOf) || 1]).range([2.5, 10]);
    const toneOn = layer === "C" && L && document.getElementById("net-tone").checked;
    const wExtent = d3.extent(net.edges, (e) => e[2]);
    const fade = layer === "C" ? () => (toneOn ? 0.5 : 0.22) : d3.scaleLinear().domain(wExtent[0] === wExtent[1] ? [0, 1] : wExtent).range([0.1, 0.42]);
    const neighbours = new Set();
    if (selected) net.edges.forEach(([a, b]) => { if (a === selected) neighbours.add(b); if (b === selected) neighbours.add(a); });
    const links = svg.append("g");
    net.edges.forEach((e) => {
      const [a, b, w] = e;
      const A = byId.get(a); const B = byId.get(b);
      if (!A || !B || A.x === null || B.x === null) return;
      const lit = selected && (a === selected || b === selected);
      const tone = toneOn && e[3] ? toneOf(e[3]) : null;
      const color = tone ? TONE[tone] : lit ? COLOR.ink : COLOR.placebo;
      const strokeW = layer === "C" ? Math.min(3, 0.8 + w / 8) : 0.6 + 1.6 * ((w - wExtent[0]) / ((wExtent[1] - wExtent[0]) || 1));
      links.append("line").attr("x1", x(A.x)).attr("y1", y(A.y)).attr("x2", x(B.x)).attr("y2", y(B.y))
        .attr("stroke", color).attr("stroke-opacity", lit ? 0.85 : selected ? 0.08 : fade(w))
        .attr("stroke-width", lit ? Math.max(1.2, strokeW) : layer === "C" ? (tone ? 1.1 : 0.8) : strokeW);
    });
    const group = svg.append("g");
    nodes.forEach((n) => {
      const matches = !partyFilter || n.party === partyFilter;
      const dim = !matches || (selected && n.id !== selected && !neighbours.has(n.id));
      const tip = layer === "C" ? [`${n.party}, ${n.side}`, `Made ${n.made}, received ${n.received}`] : [`${n.party}, ${n.side}`, `${degree.get(n.id) || 0} lines drawn`];
      const g = group.append("g").attr("class", "node").attr("transform", `translate(${x(n.x)},${y(n.y)})`).attr("tabindex", matches ? 0 : -1).attr("role", "button").attr("aria-label", `${n.name}, ${n.party}`)
        .on("click", () => selectMember(n.id))
        .on("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectMember(n.id); } })
        .on("pointermove", (event) => showTip(event, n.name, tip))
        .on("pointerleave", hideTip);
      g.append("circle").attr("r", Math.max(r(sizeOf(n)), 11)).attr("fill", "transparent");
      g.append("circle").attr("class", "mark").attr("r", r(sizeOf(n))).attr("fill", n.side === "government" ? COLOR.together : COLOR.apart)
        .attr("fill-opacity", dim ? 0.14 : 0.95).attr("stroke", n.id === selected ? COLOR.ink : COLOR.paper).attr("stroke-width", n.id === selected ? 2.5 : 1);
    });
    if (selected && byId.get(selected) && byId.get(selected).x !== null) {
      const n = byId.get(selected);
      const side = x(n.x) > width * 0.7 ? "end" : "start";
      svg.append("text").attr("x", x(n.x) + (side === "start" ? 12 : -12)).attr("y", y(n.y) + 4).attr("text-anchor", side).attr("class", "strong").style("paint-order", "stroke").style("stroke", COLOR.paper).style("stroke-width", "3px").text(n.name);
    }
    const items = [{ color: COLOR.together, label: "Government party" }, { color: COLOR.apart, label: "Outside government" }, { color: COLOR.placebo, label: LAYER_UI[layer].size }];
    if (toneOn) items.push({ color: TONE.hostile, label: "Mostly hostile", line: true }, { color: TONE.neutral, label: "Mixed / neutral", line: true }, { color: TONE.friendly, label: "Mostly friendly", line: true });
    else if (layer !== "C") items.push({ color: COLOR.placebo, label: "Thicker line: more similar", line: true });
    legend("legend-net", items);
    renderPanel(layer, net, byId);

    if (net.stats) {
      const s = net.stats;
      stats.hidden = false;
      stats.textContent = `This layer, ${name}: ${fmt(s.members)} members, ${fmt(s.edges)} lines. Louvain finds ${s.communities} communities (modularity ${s.modularity.toFixed(2)}), which match party with NMI ${s.nmi_party.toFixed(2)}. Assortativity by party ${s.assort_party.toFixed(2)}, by government side ${s.assort_side.toFixed(2)}.`;
    } else stats.hidden = true;

    if (layer === "C") {
      const w = D.per_window[name];
      setNumber("backboneEdges", fmt(net.edges.length));
      setNumber("membersDrawn", `${fmt(net.drawn)} of ${fmt(net.nodes.length)}`);
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
      if (net.tone_counts) {
        const t = net.tone_counts; const total = t.hostile + t.neutral + t.friendly;
        setNumber("toneShares", `${pct(t.hostile / total)} hostile, ${pct(t.neutral / total)} neutral and ${pct(t.friendly / total)} friendly, of ${fmt(total)} scored challenges`);
      }
    }
  }

  function selectMember(id) {
    selected = selected === id ? null : id;
    drawNetwork();
  }

  function memberList(title, list, byId, value) {
    const head = document.createElement("h5"); head.textContent = title;
    const ol = document.createElement("ol");
    list.forEach(([id, v]) => {
      const other = byId.get(id);
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.textContent = other ? `${other.name} (${other.party})` : String(id);
      button.addEventListener("click", () => { selected = id; drawNetwork(); });
      const n = document.createElement("span"); n.textContent = value ? value(v, other) : v;
      li.append(button, n); ol.append(li);
    });
    return [head, ol];
  }

  function toneBar(t) {
    const total = t[0] + t[1] + t[2];
    const wrap = document.createElement("div");
    if (!total) return wrap;
    const bar = document.createElement("div"); bar.className = "tone-bar";
    ["hostile", "neutral", "friendly"].forEach((k, i) => {
      const s = document.createElement("span"); s.style.width = (100 * t[i] / total) + "%"; s.style.background = TONE[k]; bar.append(s);
    });
    const text = document.createElement("div"); text.className = "wlf-muted";
    text.textContent = `Tone of challenges made: ${pct(t[0] / total)} hostile, ${pct(t[1] / total)} neutral, ${pct(t[2] / total)} friendly`;
    wrap.append(bar, text);
    return wrap;
  }

  function renderPanel(layer, net, byId) {
    const panel = document.getElementById("member-panel");
    panel.replaceChildren();
    const member = selected ? byId.get(selected) : null;
    if (!member) {
      const p = document.createElement("p");
      p.className = "wlf-muted";
      p.textContent = selected && net ? "This member is not in this layer for this period."
        : layer === "C" ? "Click a member to see who they challenged most and who challenged them."
        : "Click a member to see who they are most alike in this layer.";
      panel.append(p);
      return;
    }
    const h = document.createElement("h4"); h.textContent = member.name;
    const sub = document.createElement("div"); sub.className = "wlf-muted";
    panel.append(h, sub);
    if (layer === "C") {
      sub.textContent = `${member.party}, ${member.side}. Made ${member.made}, received ${member.received}.`;
      if (member.tone) panel.append(toneBar(member.tone));
      if (member.emoji && member.emoji.length && L.emoji) {
        const e = document.createElement("div"); e.className = "member-emoji";
        e.textContent = member.emoji.map((i) => L.emoji.emoji[i]).join(" ");
        const note = document.createElement("div"); note.className = "wlf-muted"; note.textContent = "Most typical DeepMoji emoji in their challenges, relative to the chamber";
        panel.append(e, note);
      }
      panel.append(...memberList("Challenged most", member.out, byId), ...memberList("Challenged most by", member.in, byId));
      return;
    }
    sub.textContent = `${member.party}, ${member.side}.`;
    if (layer === "E" && member.member_of) {
      const names = L.committees[windowValue()];
      const head = document.createElement("h5"); head.textContent = `Committees (${member.member_of.length})`;
      const p = document.createElement("p"); p.className = "committee-list"; p.textContent = member.member_of.map((i) => names[i]).join(", ");
      panel.append(head, p);
      const mine = new Set(member.member_of);
      panel.append(...memberList(LAYER_UI.E.lists[0][0], member.top, byId, (v, other) => other && other.member_of ? `${other.member_of.filter((i) => mine.has(i)).length} shared` : v.toFixed(2)));
      return;
    }
    const [title, value] = LAYER_UI[layer].lists[0];
    panel.append(...memberList(title, member.top, byId, value));
  }

  function fillNetworkControls() {
    const net = currentNet(layerValue(), windowValue());
    const nodes = net ? net.nodes : [];
    const partySelect = document.getElementById("net-party");
    const current = partySelect.value;
    partySelect.replaceChildren(new Option("All parties", ""), ...[...new Set(nodes.map((n) => n.party))].sort().map((p) => new Option(p, p)));
    partySelect.value = [...partySelect.options].some((o) => o.value === current) ? current : "";
    const list = document.getElementById("member-list");
    list.replaceChildren(...nodes.map((n) => n.name).sort().map((v) => { const o = document.createElement("option"); o.value = v; return o; }));
  }

  /* ---------- Figure 5b: challenges vs committees ---------- */
  function drawCompare() {
    if (!L) return;
    const rows = L.windows.map((w) => {
      const c = L.correlations[w];
      if (!c) return null;
      const i = c.layers.indexOf("C"); const j = c.layers.indexOf("E");
      return i < 0 || j < 0 ? null : { w, rho: c.rho[i][j], pairs: c.pairs, members: c.members };
    }).filter(Boolean);
    const label = (w) => { const row = D.windows.find((x) => x.name === w); return `${row.government.join("+")} ${row.from.slice(0, 4)}`; };
    const host = document.getElementById("fig-compare");
    const width = Math.max(host.clientWidth, 280);
    const left = Math.min(150, width * 0.38);
    const frame = svgFor("fig-compare", 30 + rows.length * 30, { top: 8, right: 40, bottom: 22, left });
    const { svg, inner } = frame;
    const top = Math.max(0.3, d3.max(rows, (r) => r.rho));
    const x = d3.scaleLinear().domain([Math.min(0, d3.min(rows, (r) => r.rho)), top]).nice().range([inner.left, inner.right]);
    const y = d3.scaleBand().domain(rows.map((r) => r.w)).range([inner.top, inner.bottom]).padding(0.35);
    svg.append("g").attr("transform", `translate(0,${inner.bottom})`).call(d3.axisBottom(x).ticks(5).tickSize(-(inner.bottom - inner.top))).call((g) => g.select(".domain").remove());
    rows.forEach((r) => {
      svg.append("text").attr("x", inner.left - 8).attr("y", y(r.w) + y.bandwidth() / 2 + 4).attr("text-anchor", "end").text(label(r.w));
      svg.append("rect").attr("x", x(Math.min(0, r.rho))).attr("y", y(r.w)).attr("width", Math.abs(x(r.rho) - x(0))).attr("height", y.bandwidth())
        .attr("fill", COLOR.together).attr("rx", 2)
        .on("pointermove", (event) => showTip(event, label(r.w), [`Spearman ρ = ${r.rho.toFixed(3)}`, `${fmt(r.pairs)} pairs of ${fmt(r.members)} members`]))
        .on("pointerleave", hideTip);
      svg.append("text").attr("x", x(r.rho) + 5).attr("y", y(r.w) + y.bandwidth() / 2 + 4).text(r.rho.toFixed(2));
    });
    svg.append("line").attr("x1", x(0)).attr("x2", x(0)).attr("y1", inner.top).attr("y2", inner.bottom).attr("stroke", COLOR.ink);
    legend("legend-compare", [{ color: COLOR.together, label: "Spearman ρ: challenges exchanged vs committee overlap, per pair of members" }]);
    drawLayerStats();
  }

  function drawLayerStats() {
    if (!L) return;
    const name = windowValue();
    const rows = Object.keys(L.layers).map((k) => {
      const s = (L.networks[k][name] || {}).stats;
      const lab = `${k}. ${L.layers[k].name}`;
      return s ? [lab, fmt(s.members), fmt(s.edges), s.communities, s.modularity.toFixed(2), s.nmi_party.toFixed(2), s.assort_party.toFixed(2), s.assort_side.toFixed(2)]
        : [lab, "–", "–", "–", "–", "–", "–", "–"];
    });
    makeTable(document.getElementById("table-layer-stats"), [`Layer (${name})`, "Members", "Lines", "Communities", "Modularity", "NMI with party", "Assort. party", "Assort. side"], rows, [1, 2, 3, 4, 5, 6, 7]);
  }

  /* ---------- Figure 5c: DeepMoji ---------- */
  const EMOTION_COLOR = { anger: COLOR.apart, disapproval: "#d9822b", sadness: "#6b5b95", laughter: "#c9a227", happy: "#2f7d4f", love: COLOR.together, other: "#a39a8c" };

  function drawEmoji() {
    if (!L || !L.emoji) return;
    const em = L.emoji;
    const measure = document.getElementById("emoji-measure").value;
    const values = em[measure];
    const groupOf = {};
    Object.entries(em.groups).forEach(([g, ids]) => ids.forEach((i) => { groupOf[i] = g; }));
    const host = document.getElementById("fig-emoji");
    const width = Math.max(host.clientWidth, 280);
    const shown = width < 520 ? 16 : width < 800 ? 24 : 32;
    setNumber("emojiShown", shown);
    const order = values.map((v, i) => i).sort((a, b) => values[b] - values[a]).slice(0, shown);
    const total = d3.sum(values);
    const frame = svgFor("fig-emoji", 230, { top: 10, right: 8, bottom: 34, left: 46 });
    const { svg, inner } = frame;
    const x = d3.scaleBand().domain(order).range([inner.left, inner.right]).padding(0.18);
    const y = d3.scaleLinear().domain([0, d3.max(order, (i) => values[i] / total)]).nice().range([inner.bottom, inner.top]);
    svg.append("g").attr("transform", `translate(${inner.left},0)`).call(d3.axisLeft(y).ticks(4).tickFormat((v) => pct(v)).tickSize(-(inner.right - inner.left))).call((g) => g.select(".domain").remove());
    order.forEach((i) => {
      svg.append("rect").attr("x", x(i)).attr("y", y(values[i] / total)).attr("width", x.bandwidth()).attr("height", inner.bottom - y(values[i] / total))
        .attr("fill", EMOTION_COLOR[groupOf[i]]).attr("rx", 1.5)
        .on("pointermove", (event) => showTip(event, `${em.emoji[i]} ${em.names[i].replace(/_/g, " ")}`, [groupOf[i], measure === "mean_prob" ? `mean probability ${pct(values[i] / total, 1)}` : `top pick for ${fmt(values[i])} challenges (${pct(values[i] / total, 1)})`]))
        .on("pointerleave", hideTip);
      svg.append("text").attr("x", x(i) + x.bandwidth() / 2).attr("y", inner.bottom + 22).attr("text-anchor", "middle").style("font-size", Math.min(18, x.bandwidth()) + "px").text(em.emoji[i]);
    });
    legend("legend-emoji", Object.keys(em.groups).map((g) => ({ color: EMOTION_COLOR[g], label: g })));

    const sframe = svgFor("fig-sentiment", 240, { top: 14, right: 8, bottom: 40, left: 46 });
    const centers = em.bins.slice(0, -1).map((b, k) => (b + em.bins[k + 1]) / 2);
    const series = [["Aimed at the government", em.hist_at_government, COLOR.together], ["Aimed at the opposition", em.hist_at_opposition, COLOR.apart]]
      .map(([label, h, color]) => { const n = d3.sum(h); return { label, color, share: h.map((v) => v / n) }; });
    const sx = d3.scaleLinear().domain([em.bins[0], em.bins[em.bins.length - 1]]).range([sframe.inner.left, sframe.inner.right]);
    const sy = d3.scaleLinear().domain([0, d3.max(series, (d) => d3.max(d.share))]).nice().range([sframe.inner.bottom, sframe.inner.top]);
    const g = sframe.svg;
    g.append("g").attr("transform", `translate(0,${sframe.inner.bottom})`).call(d3.axisBottom(sx).ticks(8));
    g.append("g").attr("transform", `translate(${sframe.inner.left},0)`).call(d3.axisLeft(sy).ticks(4).tickFormat((v) => pct(v)).tickSize(-(sframe.inner.right - sframe.inner.left))).call((a) => a.select(".domain").remove());
    const cut = L.settings.tone_cut;
    [-cut, cut].forEach((c) => g.append("line").attr("x1", sx(c)).attr("x2", sx(c)).attr("y1", sframe.inner.top).attr("y2", sframe.inner.bottom).attr("stroke", COLOR.ink).attr("stroke-dasharray", "3 3").attr("stroke-opacity", 0.5));
    g.append("text").attr("x", sx(-cut) - 4).attr("y", sframe.inner.top + 4).attr("text-anchor", "end").text("\u2190 hostile");
    g.append("text").attr("x", sx(cut) + 4).attr("y", sframe.inner.top + 4).text("friendly \u2192");
    g.append("text").attr("x", (sframe.inner.left + sframe.inner.right) / 2).attr("y", sframe.inner.bottom + 34).attr("text-anchor", "middle").text("Sentiment: P(happy + love emoji) \u2212 P(anger + disapproval emoji)");
    series.forEach((d) => {
      g.append("path").datum(d.share).attr("fill", d.color).attr("fill-opacity", 0.12).attr("stroke", d.color).attr("stroke-width", 2)
        .attr("d", d3.area().x((v, k) => sx(centers[k])).y0(sframe.inner.bottom).y1((v) => sy(v)).curve(d3.curveMonotoneX));
    });
    legend("legend-sentiment", series.map((d) => ({ color: d.color, label: d.label, line: true })).concat([{ color: COLOR.ink, label: "Tone cut-offs (dashed)", line: true }]));
  }

  // Worked examples (data/emoji_examples.json, archetypes/deepmoji.py --examples): Danish, English, emoji.
  function drawEmojiExamples() {
    if (!X || !L || !L.emoji) return;
    const em = L.emoji;
    const groupOf = {};
    Object.entries(em.groups).forEach(([g, ids]) => ids.forEach((i) => { groupOf[i] = g; }));
    const el = (tag, className, text) => {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    };
    const chips = (top, n) => {
      const box = el("div", "emoji-chips");
      top.slice(0, n).forEach(([i, p]) => {
        const name = em.names[i].replace(/_/g, " ");
        const chip = el("span", "emoji-chip");
        chip.style.borderBottomColor = EMOTION_COLOR[groupOf[i]];
        chip.title = `${name} (${groupOf[i]})`;
        const face = el("span", "face", em.emoji[i]);
        face.setAttribute("role", "img");
        face.setAttribute("aria-label", name);
        chip.append(face, el("span", "share", pct(p, 1)));
        box.append(chip);
      });
      return box;
    };
    const cell = (label, content, lang) => {
      const d = el("div");
      d.append(el("span", "step", label));
      if (lang) { const p = el("p", "", content); p.lang = lang; d.append(p); } else d.append(content);
      return d;
    };
    const cut = L.settings.tone_cut;
    const list = document.getElementById("emoji-example-list");
    list.replaceChildren();
    X.examples.forEach((x) => {
      const card = el("article", "emoji-example");
      const head = el("div", "emoji-example-head");
      const date = new Date(x.date + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
      head.append(el("span", "", `${x.from} member to ${x.to === "a minister" ? x.to : x.to + " member"}, ${date}`),
        el("span", "how", x.how === "chosen" ? "Picked as a failure" : "Random draw"));
      card.append(head);
      x.sentences.forEach((s) => {
        const row = el("div", "emoji-steps");
        row.append(cell("Danish", s.da, "da"), cell("Translated", s.en, "en"), cell("DeepMoji", chips(s.top, 3)));
        card.append(row);
      });
      // Adding 0 turns a rounded -0 into 0.
      const score = (Math.round(x.sentiment * 100) / 100 + 0).toFixed(2).replace("-", "\u2212");
      const tone = x.sentiment <= -cut ? "hostile" : x.sentiment >= cut ? "friendly" : "neutral";
      const result = el("div", "emoji-result");
      result.append(el("span", "step", x.sentences.length > 1 ? `Whole remark, mean of ${x.sentences.length} sentences` : "Whole remark"),
        chips(x.top, 5), el("span", "verdict", `Sentiment ${score}: ${tone}`));
      card.append(result);
      list.append(card);
    });
    setNumber("exPool", fmt(X.pool));
    setNumber("exWords", X.words.join("\u2013"));
    setNumber("exLeft", pct(X.venstre_as_left));
    setNumber("exVenstre", fmt(X.venstre_sentences));
    setNumber("exCut", pct(X.cut_at_hr));
    document.getElementById("emoji-examples").hidden = false;
  }

  function layerNumbers() {
    if (!L) return;
    const s = L.settings;
    setNumber("kNeighbours", s.k_neighbours);
    setNumber("minSharedVotes", s.min_shared_votes);
    setNumber("toneCut", s.tone_cut.toFixed(2));
    const em = L.emoji;
    setNumber("emojiChallenges", fmt(em.challenges));
    setNumber("sentGov", em.mean_at_government.toFixed(3));
    setNumber("sentOpp", em.mean_at_opposition.toFixed(3));
    const groups = Object.keys(em.groups);
    makeTable(document.getElementById("table-emotions"), ["Government", "Challenges", ...groups.map((g) => `${g} ${em.groups[g].slice(0, 4).map((i) => em.emoji[i]).join("")}`)],
      Object.entries(em.groups_by_window).map(([w, v]) => [w, fmt(v.challenges), ...groups.map((g) => pct(v[g], 1))]), groups.map((_, i) => i + 1));
    const check = L.tone.hand_labels || {};
    setNumber("toneCheck", check.status === "labeled"
      ? `Checked against ${check.rows} challenges hand-labelled by one member of the group, the three categories agree with the hand label on only ${pct(check.accuracy)}, less than always answering "${check.majority_label}" (${pct(check.majority_baseline)}): DeepMoji calls many neutral remarks friendly. Its underlying score does put remarks in the right order (hostile against the rest: AUC ${check.auc_hostile.toFixed(2)}; Spearman ${check.spearman.toFixed(2)} with the labels, p = ${check.spearman_p.toFixed(3)}), so read the colours as harsher or friendlier than usual, not as a verdict on single remarks.`
      : `It is not validated yet: the group's hand-labelled tone sheet (labeling/challenge_stance.csv) is ${check.status || "missing"}.`);
    makeTable(document.getElementById("table-layer-defs"), ["Layer", "What a line represents", "Edge property"],
      Object.entries(L.layers).map(([k, v]) => [`${k}. ${v.name}`, v.edge, v.property]));
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
    if (!L) {
      document.getElementById("net-layer").disabled = true;
      document.getElementById("layers").hidden = true;
      document.getElementById("emoji").hidden = true;
      document.querySelectorAll(".needs-layers").forEach((el) => { el.hidden = true; });
    }
    fillNumbers(); drawTables(); layerNumbers(); drawEmojiExamples();
    fillNetworkControls();
    const drawAll = () => { drawTimeline(); drawLayers(); drawRole(); drawMatrix(); drawNetwork(); drawCompare(); drawEmoji(); };
    eventSelect.addEventListener("change", drawTimeline);
    document.getElementById("matrix-select").addEventListener("change", drawMatrix);
    document.getElementById("emoji-measure").addEventListener("change", drawEmoji);
    ["net-layer", "net-window"].forEach((id) => document.getElementById(id).addEventListener("change", () => { fillNetworkControls(); drawNetwork(); drawLayerStats(); }));
    document.getElementById("net-party").addEventListener("change", drawNetwork);
    document.getElementById("net-tone").addEventListener("change", drawNetwork);
    document.getElementById("net-member").addEventListener("change", (e) => {
      const net = currentNet(layerValue(), windowValue());
      const m = net && net.nodes.find((n) => n.name === e.target.value);
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

  // layers.json and emoji_examples.json are optional: without them the page still draws everything else.
  const getJson = (url) => fetch(url).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
  Promise.all([getJson("data/site.json"), getJson("data/layers.json").catch(() => null), getJson("data/emoji_examples.json").catch(() => null)])
    .then(([data, layers, examples]) => { D = data; L = layers; X = examples; init(); })
    .catch((error) => {
      const p = document.createElement("p");
      p.textContent = `The figures could not load (${error.message}).`;
      document.getElementById("evidence").after(p);
    });
})();


/* Party key: on phone-sized screens start it minimised, since an open key would cover
   the text. It stays on screen as a small "Party key - show" tab the reader can open. */
(function () {
  "use strict";
  const box = document.getElementById("party-key-box");
  if (box && window.matchMedia("(max-width: 55.99rem)").matches) box.open = false;
})();
