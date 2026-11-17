/* Crossing the Aisle, Part 1: archetype figures. Draws from data/site.json ("archetypes"),
   which tools/export_site.py copies from tools/analyze_archetypes.py. Nothing is computed here
   beyond display formatting. DRAFT: style to be reworked later. */
(function () {
  "use strict";

  // Categorical slots validated against the paper surface (dataviz validator, light mode).
  const ARCH_COLOR = {
    attack_dog: "#eb6834", lightning_rod: "#eda100", negative_nancy: "#e87ba4",
    bridge_builder: "#1baf7a", defector: "#2a78d6", rebel: "#008300", none: "#b3a88f",
  };
  const DIVERGE = ["#1c5cab", "#f0efec", "#b1352a"]; // blue - neutral - red, for z-scores
  const tooltip = document.getElementById("tooltip");
  let A, LABELS;

  const fmt1 = (v) => (v == null ? "–" : Number(v).toFixed(1));
  const fmt2 = (v) => (v == null ? "–" : Number(v).toFixed(2));
  const pct = (v, d = 0) => (v == null ? "–" : (v * 100).toFixed(d) + "%");
  const archName = (k) => (k === "none" ? "No archetype" : A.archetypes[k].name);
  const el = (tag, attrs = {}, text) => {
    const e = document.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => (k === "class" ? (e.className = v) : e.setAttribute(k, v)));
    if (text != null) e.textContent = text;
    return e;
  };
  const setA = (key, value) => document.querySelectorAll(`[data-a="${key}"]`).forEach((n) => { n.textContent = value; });

  function showTip(event, title, lines) {
    tooltip.replaceChildren(el("strong", {}, title));
    lines.forEach((l) => tooltip.append(el("div", {}, l)));
    tooltip.hidden = false;
    const box = tooltip.getBoundingClientRect();
    tooltip.style.left = Math.max(6, Math.min(window.innerWidth - box.width - 6, event.clientX + 14)) + "px";
    tooltip.style.top = Math.max(6, event.clientY - box.height - 10) + "px";
  }
  const hideTip = () => { tooltip.hidden = true; };

  function table(container, headers, rows, numeric = []) {
    const t = el("table", { class: "data" });
    const h = t.createTHead().insertRow();
    headers.forEach((x, i) => h.append(el("th", numeric.includes(i) ? { class: "num" } : {}, x)));
    const b = t.createTBody();
    rows.forEach((r) => {
      const tr = b.insertRow();
      r.forEach((c, i) => {
        const td = tr.insertCell();
        if (numeric.includes(i)) td.className = "num";
        if (c instanceof Node) td.append(c); else td.textContent = c;
      });
    });
    container.replaceChildren(t);
    return t;
  }

  function legend(container, keys) {
    container.replaceChildren(...keys.map((k) => {
      const s = el("span");
      s.append(el("span", { class: "arch-chip", style: `background:${ARCH_COLOR[k]}` }), archName(k));
      return s;
    }));
  }

  const width = (host) => Math.max(300, host.clientWidth || 700);

  /* ---------- headline numbers and status ---------- */
  function numbers() {
    const c = A.clusters.all_measures;
    setA("profiled", A.counts.members_profiled);
    setA("minMade", A.settings.min_made);
    setA("scored", A.counts.challenges_scored.toLocaleString("en-GB"));
    setA("k", c.k);
    setA("silhouette", c.silhouette_by_k[c.k].toFixed(2));
    setA("spearman", A.made_received_spearman.toFixed(2));
    const enter = A.over_time.events.find((e) => e.event === "party entered government");
    if (enter) setA("enterDrop", `${fmt1(enter.made_per_year_before)} → ${fmt1(enter.made_per_year_after)}`);
    const al = A.overlaps.find((o) => o.a === "attack_dog" && o.b === "lightning_rod");
    setA("overlapAL", `${al.both} of ${A.counts.attack_dog} attack dogs`);
    setA("nFeatures", Object.keys(A.features).length);
    setA("nSeeds", 20);
    setA("negShare", pct(A.tone_overall.negative_share));
    setA("minWindow", 10);
    document.querySelectorAll("[data-l]").forEach((n) => {
      const r = (LABELS || {})[n.dataset.l] || {};
      n.textContent = r.status === "labeled" || r.status === "partial"
        ? `${r.status}: ${r.n} of ${r.of} rows` + (r.share != null ? `, ${pct(r.share)} yes` : "")
        : "not labeled yet";
    });
  }

  /* ---------- Figure 1.1: made vs received ---------- */
  function scatter() {
    const host = document.getElementById("fig-arch-scatter");
    const partySel = document.getElementById("arch-party");
    const search = document.getElementById("arch-member");
    const members = A.members.filter((m) => m.made_per_year > 0);
    const parties = [...new Set(members.map((m) => m.party))].filter(Boolean).sort();
    partySel.replaceChildren(el("option", { value: "" }, "All parties"), ...parties.map((p) => el("option", { value: p }, p)));
    document.getElementById("arch-member-list").replaceChildren(...members.map((m) => el("option", { value: m.name })));
    legend(document.getElementById("legend-arch"), [...Object.keys(A.archetypes), "none"]);

    const W = width(host), H = Math.min(520, Math.max(340, W * 0.62));
    const m = { t: 14, r: 16, b: 44, l: 56 };
    const svg = d3.select(host).html("").append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
      .attr("aria-label", "Scatter of challenges made against challenges received per year, one dot per member");
    const x = d3.scaleLog().domain([1, d3.max(members, (d) => d.made_per_year) * 1.1]).range([m.l, W - m.r]).clamp(true);
    const y = d3.scaleLog().domain([0.5, d3.max(members, (d) => d.received_per_year) * 1.1]).range([H - m.b, m.t]).clamp(true);
    svg.append("g").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(6, "~s").tickSize(-(H - m.t - m.b)));
    svg.append("g").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(6, "~s").tickSize(-(W - m.l - m.r)));
    svg.append("text").attr("x", (W + m.l) / 2).attr("y", H - 8).attr("text-anchor", "middle").text("Challenges made per year (log)");
    svg.append("text").attr("transform", `translate(14,${(H - m.b) / 2}) rotate(-90)`).attr("text-anchor", "middle").text("Received per year (log)");
    const th = A.thresholds;
    svg.append("line").attr("x1", x(th.made_per_year)).attr("x2", x(th.made_per_year)).attr("y1", m.t).attr("y2", H - m.b)
      .attr("stroke", "#5b4f3f").attr("stroke-dasharray", "4 4");
    svg.append("line").attr("y1", y(th.received_per_year)).attr("y2", y(th.received_per_year)).attr("x1", m.l).attr("x2", W - m.r)
      .attr("stroke", "#5b4f3f").attr("stroke-dasharray", "4 4");
    svg.append("text").attr("x", x(th.made_per_year) + 4).attr("y", m.t + 10).text("attack dog →");
    svg.append("text").attr("x", W - m.r - 4).attr("y", y(th.received_per_year) - 5).attr("text-anchor", "end").text("lightning rod ↑");

    const ordered = members.slice().sort((a, b) => (a.primary === "none") - (b.primary === "none")).reverse();
    const dots = svg.append("g").selectAll("circle").data(ordered).join("circle")
      .attr("class", "dot").attr("r", 5).attr("cx", (d) => x(d.made_per_year)).attr("cy", (d) => y(Math.max(d.received_per_year, 0.5)))
      .attr("fill", (d) => ARCH_COLOR[d.primary])
      .on("mousemove", (e, d) => showTip(e, `${d.name} (${d.party})`, [
        `Archetypes: ${d.archetypes.length ? d.archetypes.map(archName).join(", ") : "none"}`,
        `Made ${fmt1(d.made_per_year)} / year · received ${fmt1(d.received_per_year)} / year`,
        `Tone ${fmt2(d.tone)} · ${pct(d.cross_bloc_share)} at other bloc`,
        `Parties: ${d.parties} · cluster ${d.cluster}`]))
      .on("mouseleave", hideTip);

    function update() {
      const p = partySel.value, q = search.value.trim().toLowerCase();
      dots.classed("dim", (d) => (p && d.party !== p) || (q && !d.name.toLowerCase().includes(q)))
        .classed("hit", (d) => q && d.name.toLowerCase() === q);
      memberTable(p, q);
    }
    partySel.onchange = update; search.oninput = update;
    update();
  }

  function memberTable(party, q) {
    const rows = A.members
      .filter((m) => (!party || m.party === party) && (!q || m.name.toLowerCase().includes(q)))
      .sort((a, b) => b.made - a.made)
      .map((m) => [m.name, m.party, m.parties, fmt1(m.made_per_year), fmt1(m.received_per_year), fmt2(m.tone),
        pct(m.cross_bloc_share), m.rebel_rate == null ? "–" : pct(m.rebel_rate, 2), m.archetypes.map(archName).join(", ") || "–", m.cluster]);
    table(document.getElementById("table-arch-members"),
      ["Member", "Party", "Party history", "Made / yr", "Received / yr", "Tone", "At other bloc", "Rebel rate", "Archetypes", "Cluster"],
      rows, [3, 4, 5, 6, 7, 9]);
  }

  /* ---------- Figure 1.2: profiles heatmap ---------- */
  function profiles() {
    const host = document.getElementById("fig-arch-profiles");
    const feats = Object.keys(A.features);
    const rows = Object.keys(A.archetype_profiles).map((k) => ({ label: A.archetypes[k].name, key: k, profile: A.archetype_profiles[k].profile, uses: A.archetype_profiles[k].uses, n: A.archetype_profiles[k].n }))
      .concat(A.clusters.described.map((c) => ({ label: `Cluster ${c.cluster}`, key: "c" + c.cluster, profile: c.profile, uses: [], n: c.size })));
    const W = Math.max(width(host), 640), cellW = (W - 170) / feats.length, cellH = 26, top = 150;
    const H = top + rows.length * cellH + 20;
    const svg = d3.select(host).html("").append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
      .attr("aria-label", "Heatmap of mean standardised measures per archetype and cluster");
    const color = d3.scaleLinear().domain([-1.5, 0, 1.5]).range(DIVERGE).clamp(true);
    feats.forEach((f, j) => {
      svg.append("text").attr("transform", `translate(${170 + j * cellW + cellW / 2},${top - 6}) rotate(-55)`)
        .text(f.replace(/_/g, " ")).append("title").text(A.features[f].label);
    });
    rows.forEach((r, i) => {
      const yy = top + i * cellH + (r.key.startsWith("c") ? 10 : 0);
      svg.append("text").attr("x", 0).attr("y", yy + cellH / 2 + 4).attr("class", "strong").text(`${r.label} (${r.n})`);
      feats.forEach((f, j) => {
        const v = r.profile[f];
        svg.append("rect").attr("x", 170 + j * cellW + 1).attr("y", yy + 1).attr("width", cellW - 2).attr("height", cellH - 2).attr("rx", 3)
          .attr("fill", color(v)).attr("stroke", r.uses.includes(f) ? "#2b2622" : "none").attr("stroke-width", 2)
          .on("mousemove", (e) => showTip(e, `${r.label}: ${A.features[f].label}`, [`${fmt2(v)} SD from the average member`, r.uses.includes(f) ? "Used by the rule" : "Not used by the rule"]))
          .on("mouseleave", hideTip);
      });
    });
    document.getElementById("legend-profiles").innerHTML =
      `<span><span class="arch-chip" style="background:${DIVERGE[0]}"></span>below average</span>` +
      `<span><span class="arch-chip" style="background:${DIVERGE[1]}"></span>average</span>` +
      `<span><span class="arch-chip" style="background:${DIVERGE[2]}"></span>above average (±1.5 SD and beyond)</span>` +
      `<span>outlined = used by the rule</span>`;

    table(document.getElementById("arch-rules"), ["Archetype", "Rule (draft)", "Members", "Beyond the rule: network / tone / career (mean |z|)"],
      Object.entries(A.archetypes).map(([k, a]) => {
        const p = A.archetype_profiles[k] || {}; const b = p.beyond_rule_mean_abs_z || {};
        const name = el("span"); name.append(el("span", { class: "arch-chip", style: `background:${ARCH_COLOR[k]}` }), a.name);
        return [name, a.rule, A.counts[k], `${fmt2(b.network)} / ${fmt2(b.tone)} / ${fmt2(b.career)}`];
      }), [2]);
    const keys = Object.keys(A.archetypes);
    const both = (a, b) => (A.overlaps.find((o) => (o.a === a && o.b === b) || (o.a === b && o.b === a)) || {}).both;
    table(document.getElementById("table-arch-overlap"), ["", ...keys.map(archName)],
      keys.map((a) => [archName(a), ...keys.map((b) => (a === b ? A.counts[a] : both(a, b)))]), keys.map((_, i) => i + 1));
  }

  /* ---------- Figure 1.3: clusters ---------- */
  function clusters() {
    const c = A.clusters;
    table(document.getElementById("arch-clusters"), ["Cluster", "Members", "Stands out on (z)", "Archetypes inside", "Main parties", "Most active members"],
      c.described.map((d) => [d.cluster, d.size,
        d.stands_out_on.map((s) => `${s.feature.replace(/_/g, " ")} ${s.z > 0 ? "+" : ""}${s.z}`).join("; "),
        d.archetypes.filter(([k]) => k !== "none").map(([k, n]) => `${archName(k)} ${n}`).join(", "),
        Object.entries(d.parties).map(([p, n]) => `${p} ${n}`).join(", "), d.examples.slice(0, 4).join(", ")]), [0, 1]);
    const a = c.ari_with_primary_archetype;
    document.getElementById("arch-cluster-text").textContent =
      `silhouette is highest at k = ${c.all_measures.k} (${c.all_measures.silhouette_by_k[c.all_measures.k].toFixed(2)}), with seed stability ARI ${c.all_measures.seed_stability_ari}. ` +
      `Agreement with the rule-based archetypes is low (ARI ${a.all_measures}); clustering on tone measures only agrees best (ARI ${a.tone_only}), on network measures only ${a.network_only}. ` +
      `Network-only and tone-only clusterings barely agree with each other (ARI ${c.ari_network_vs_tone}), so tone and network position are two separate dimensions of a member's role.`;
  }

  /* ---------- Figure 1.4: parties ---------- */
  function parties() {
    const keys = Object.keys(A.archetypes);
    const t = table(document.getElementById("arch-party-table"), ["Party", "Bloc", "Members", ...keys.map(archName)],
      A.by_party.map((p) => [p.party, p.bloc || "–", p.members, ...keys.map((k) => p[k].length || "")]), [2]);
    // Shade counts and put the names on hover.
    [...t.tBodies[0].rows].forEach((tr, i) => keys.forEach((k, j) => {
      const td = tr.cells[3 + j], names = A.by_party[i][k];
      td.className = "count" + (names.length ? " has" : "");
      if (names.length) {
        td.style.background = ARCH_COLOR[k] + Math.round(Math.min(1, names.length / 8) * 160 + 40).toString(16).padStart(2, "0");
        td.onmousemove = (e) => showTip(e, `${A.by_party[i].party}: ${archName(k)}`, names);
        td.onmouseleave = hideTip;
        td.title = names.join(", ");
      }
    }));
  }

  /* ---------- Figure 1.5: tone by target ---------- */
  function toneTarget() {
    const host = document.getElementById("fig-arch-tone");
    const rows = A.tone_by_target;
    const W = width(host), m = { t: 10, r: 20, b: 40, l: 210 }, H = m.t + m.b + rows.length * 38;
    const svg = d3.select(host).html("").append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", "Mean tone by target with intervals");
    const lo = d3.min(rows, (r) => r.ci95[0]), hi = d3.max(rows, (r) => r.ci95[1]);
    const x = d3.scaleLinear().domain([Math.min(0, lo - 0.2), hi + 0.2]).range([m.l, W - m.r]);
    const y = d3.scaleBand().domain(rows.map((r) => r.target)).range([m.t, H - m.b]).padding(0.4);
    svg.append("g").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(6).tickSize(-(H - m.t - m.b)));
    svg.append("text").attr("x", (W + m.l) / 2).attr("y", H - 6).attr("text-anchor", "middle").text("Mean tone, AFINN per 100 words (higher = friendlier)");
    const g = svg.append("g").selectAll("g").data(rows).join("g").attr("transform", (r) => `translate(0,${y(r.target) + y.bandwidth() / 2})`);
    g.append("text").attr("x", m.l - 8).attr("y", 4).attr("text-anchor", "end").attr("class", "strong").text((r) => r.target);
    g.append("line").attr("x1", (r) => x(r.ci95[0])).attr("x2", (r) => x(r.ci95[1])).attr("stroke", "#2b2622").attr("stroke-width", 2);
    g.append("circle").attr("cx", (r) => x(r.mean_tone)).attr("r", 6).attr("fill", "#2f5e6b").attr("stroke", "#fcf8ee").attr("stroke-width", 2)
      .on("mousemove", (e, r) => showTip(e, r.target, [`Mean tone ${r.mean_tone} (95% CI ${r.ci95[0]} to ${r.ci95[1]})`, `${r.n.toLocaleString("en-GB")} challenges, ${pct(r.negative_share, 1)} negative`]))
      .on("mouseleave", hideTip);
  }

  /* ---------- Figure 1.6: words ---------- */
  function words() {
    const sel = document.getElementById("arch-words-select");
    const keys = Object.keys(A.words);
    sel.replaceChildren(...keys.map((k) => el("option", { value: k }, archName(k))));
    const host = document.getElementById("fig-arch-words");
    function draw() {
      const w = A.words[sel.value];
      host.replaceChildren(...[["vs_everyone", "Against all other members"], ["vs_same_party", "Against colleagues in the same parties"]].map(([k, title]) => {
        const col = el("div"); col.append(el("h4", {}, title));
        const max = d3.max(w[k], (r) => r[1]) || 1;
        w[k].forEach(([word, z]) => {
          const row = el("div", { class: "word-row" }); row.append(el("span", {}, word));
          const bar = el("div", { class: "bar", style: `width:${Math.max(4, (z / max) * 100)}%`, title: `z = ${z}` });
          row.append(bar); col.append(row);
        });
        return col;
      }));
    }
    sel.onchange = draw; draw();
  }

  /* ---------- Figure 1.7: over time ---------- */
  function overTime() {
    const ev = A.over_time.events.slice().sort((a, b) => b.members - a.members);
    function dumbbell(id, before, after, label, digits) {
      const host = document.getElementById(id);
      const W = width(host), m = { t: 22, r: 24, b: 40, l: 230 }, H = m.t + m.b + ev.length * 34;
      const svg = d3.select(host).html("").append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", label);
      const vals = ev.flatMap((e) => [e[before], e[after]]);
      const x = d3.scaleLinear().domain([Math.min(0, d3.min(vals)), d3.max(vals) * 1.08]).range([m.l, W - m.r]);
      const y = d3.scaleBand().domain(ev.map((e) => e.event)).range([m.t, H - m.b]).padding(0.4);
      svg.append("g").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(6).tickSize(-(H - m.t - m.b)));
      svg.append("text").attr("x", (W + m.l) / 2).attr("y", H - 6).attr("text-anchor", "middle").text(label);
      svg.append("text").attr("x", m.l).attr("y", 12).text("○ before   ● after");
      const g = svg.append("g").selectAll("g").data(ev).join("g").attr("transform", (e) => `translate(0,${y(e.event) + y.bandwidth() / 2})`);
      g.append("text").attr("x", m.l - 8).attr("y", 4).attr("text-anchor", "end").attr("class", "strong").text((e) => `${e.event} (${e.members})`);
      g.append("line").attr("x1", (e) => x(e[before])).attr("x2", (e) => x(e[after])).attr("stroke", "#5b4f3f").attr("stroke-width", 2);
      g.append("circle").attr("cx", (e) => x(e[before])).attr("r", 6).attr("fill", "#fcf8ee").attr("stroke", "#2f5e6b").attr("stroke-width", 2);
      g.append("circle").attr("cx", (e) => x(e[after])).attr("r", 6).attr("fill", "#2f5e6b").attr("stroke", "#fcf8ee").attr("stroke-width", 2);
      g.on("mousemove", (evt, e) => showTip(evt, e.event, [`${e.members} members`, `Before ${e[before].toFixed(digits)} → after ${e[after].toFixed(digits)}`]))
        .on("mouseleave", hideTip);
    }
    dumbbell("fig-arch-time", "made_per_year_before", "made_per_year_after", "Median challenges made per year", 1);
    dumbbell("fig-arch-time-tone", "tone_before", "tone_after", "Mean tone of challenges (higher = friendlier)", 2);
    table(document.getElementById("table-arch-time"), ["What happened", "Members", "Made / yr before", "after", "Tone before", "after", "Attack dogs before", "after", "Negative Nancies before", "after"],
      ev.map((e) => [e.event, e.members, e.made_per_year_before, e.made_per_year_after, e.tone_before, e.tone_after,
        e.attack_dogs_before, e.attack_dogs_after, e.negative_nancies_before, e.negative_nancies_after]), [1, 2, 3, 4, 5, 6, 7, 8, 9]);
  }

  function init() {
    const steps = [numbers, scatter, profiles, clusters, parties, toneTarget, words, overTime];
    steps.forEach((f) => { try { f(); } catch (err) { console.error("[archetypes]", f.name, err); } });
  }

  fetch("data/site.json").then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }).then((d) => {
    A = d.archetypes; LABELS = d.labels;
    if (!A) { document.getElementById("archetypes").insertAdjacentText("afterend", " Run tools/analyze_archetypes.py and tools/export_site.py to fill this part."); return; }
    init();
    let t; window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => { scatter(); profiles(); toneTarget(); overTime(); }, 200); });
  }).catch((err) => console.error("[archetypes] could not load data/site.json", err));
})();
