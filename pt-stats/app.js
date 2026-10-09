/* Portuguese Anki statistics - the page reads pt-stats/data.json and draws it.
 *
 * Every number here comes from tools/pt_stats.py, which reads Anki itself: the review
 * log for each Portuguese deck, and each card's current scheduling state. Nothing is
 * typed in by hand, so refreshing the numbers means running that tool again.
 *
 * One deck is shown at a time. "All decks" adds the five together, which is why the
 * deck buttons carry their card counts - a 501-card deck and a 1124-card deck do not
 * deserve the same weight in a combined number, and it is better to see that than to
 * average it away.
 */

const PALETTE = {
  new: "#64748b",
  learning: "#fbbf24",
  young: "#38bdf8",
  mature: "#34d399",
  suspended: "#475569",
  again: "#fb7185",
  hard: "#fbbf24",
  good: "#34d399",
  easy: "#38bdf8",
  accent: "#60a5fa",
  violet: "#a78bfa",
  cyan: "#22d3ee",
  pink: "#f472b6",
};

const DECKS = [
  { id: "all", label: "All decks" },
  { id: "words", label: "words" },
  { id: "words2", label: "words2" },
  { id: "listening", label: "listening" },
  { id: "listening2", label: "listening2" },
  { id: "mnemonics", label: "mnemonics" },
];

const INK = "#e8edf7";
const MUTED = "#93a3bb";
const DAY_MS = 86400000;

const n = (value) => Number(value ?? 0).toLocaleString("en-US");
const pct = (value) => `${value}%`;
const secs = (value) => `${Number(value ?? 0).toFixed(value < 10 ? 1 : 0)}s`;
const shortDate = (date) => {
  const [, month, day] = date.split("-");
  return `${Number(month)}/${Number(day)}`;
};
const monthDay = (date) => {
  const [year, month, day] = date.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day))
    .toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
};

let DATA = null;
let selected = "all";
let live = [];

/* ---------- shared chart styling ---------- */

function tooltip(extra = {}) {
  return Object.assign({
    backgroundColor: "rgba(11,17,32,.96)",
    borderColor: "rgba(148,163,184,.3)",
    textStyle: { color: INK, fontSize: 12 },
    padding: [7, 11],
  }, extra);
}

function axisLabel(extra = {}) {
  return Object.assign({ color: MUTED, fontSize: 11 }, extra);
}

function valueAxis(extra = {}) {
  return Object.assign({
    type: "value",
    axisLabel: axisLabel(),
    axisLine: { show: false },
    splitLine: { lineStyle: { color: "rgba(148,163,184,.12)" } },
  }, extra);
}

function categoryAxis(data, extra = {}) {
  return Object.assign({
    type: "category",
    data,
    axisLabel: axisLabel(),
    axisTick: { show: false },
    axisLine: { lineStyle: { color: "rgba(148,163,184,.25)" } },
  }, extra);
}

function grid(extra = {}) {
  return Object.assign({ left: 8, right: 14, top: 34, bottom: 6, containLabel: true }, extra);
}

function legend(extra = {}) {
  return Object.assign({
    top: 0,
    textStyle: { color: MUTED, fontSize: 11 },
    itemWidth: 10,
    itemHeight: 10,
  }, extra);
}

function bar(name, data, color, extra = {}) {
  return Object.assign({
    name,
    type: "bar",
    data,
    itemStyle: { color, borderRadius: [3, 3, 0, 0] },
    barMaxWidth: 26,
  }, extra);
}

function line(name, data, color, extra = {}) {
  return Object.assign({
    name,
    type: "line",
    data,
    smooth: true,
    showSymbol: false,
    lineStyle: { width: 2, color },
    itemStyle: { color },
  }, extra);
}

/* Anki's revlog `type`: 0 first learning, 1 scheduled review, 2 relearning after a lapse.
 * The dashboard says it in the user's words instead of Anki's numbers. */
const STAGE_COLORS = [
  { key: "learning", name: "Learning", color: PALETTE.learning },
  { key: "young", name: "Young (under 21 days)", color: PALETTE.young },
  { key: "mature", name: "Mature (21 days or more)", color: PALETTE.mature },
];

/* ---------- the headline tiles ---------- */

function tiles(deck) {
  const s = DATA[deck].summary;
  const streaks = DATA[deck].streaks;
  const graduation = DATA[deck].graduation;
  const buttons = DATA[deck].buttons;
  const total = Object.values(buttons).reduce((sum, v) => sum + v, 0) || 1;
  return [
    { label: "Cards", value: n(s.cards), sub: `${n(s.started)} answered at least once` },
    { label: "Answers", value: n(s.answers), sub: `${s.reviews_per_active_day} per study day` },
    { label: "Time studied", value: `${s.hours}h`, sub: `${s.minutes_per_active_day} min per study day` },
    { label: "Study days", value: n(s.active_days),
      sub: `streak ${streaks.current}, longest ${streaks.longest}` },
    { label: "Median answer", value: secs(s.median_seconds), sub: `mean ${secs(s.mean_seconds)}` },
    { label: "Answered right", value: pct(s.pass_rate),
      sub: `${n(buttons.again)} Again of ${n(total)} answers` },
    { label: "Mature cards", value: pct(s.mature_pct),
      sub: `${n(s.standing.mature)} past 21 days · ${n(s.standing.suspended)} suspended` },
    { label: "To graduate", value: graduation.n ? n(graduation.median) : "—",
      sub: graduation.n ? `answers, over ${graduation.median_days} days` : "no card has graduated yet" },
  ];
}

function drawTiles(deck) {
  document.getElementById("kpis").innerHTML = tiles(deck).map((t) => `
    <div class="kpi">
      <div class="label">${t.label}</div>
      <div class="value">${t.value}</div>
      <div class="sub">${t.sub}</div>
    </div>`).join("");
}

/* ---------- charts, one function each ---------- */

/* Stage counts over time, replayed from the log. This is the honest "cards learned":
 * not how many were started, but how many were still three weeks out on that date. */
function growthOption(deck) {
  const series = DATA[deck].maturity_over_time;
  if (!series.length) return emptyOption("no history yet");
  return {
    tooltip: tooltip({ trigger: "axis" }),
    legend: legend(),
    grid: grid({ top: 46 }),
    xAxis: categoryAxis(series.map((s) => shortDate(s.week)), { boundaryGap: false }),
    yAxis: [
      valueAxis({ name: "cards" }),
      valueAxis({ name: "%", max: 100, position: "right", splitLine: { show: false },
                  axisLabel: axisLabel({ formatter: "{value}%" }) }),
    ],
    series: [
      ...STAGE_COLORS.map((stage) => line(stage.name, series.map((s) => s[stage.key]), stage.color, {
        stack: "stage", areaStyle: { opacity: 0.32 }, lineStyle: { width: 1, color: stage.color },
      })),
      line("Mature share", series.map((s) => s.mature_pct), PALETTE.violet,
           { yAxisIndex: 1, lineStyle: { width: 2, color: PALETTE.violet } }),
    ],
  };
}

/* A study day at a time: what was answered, and how long it took. Missing days are kept
 * as empty slots so the gaps in the habit stay visible. */
function volumeOption(deck) {
  const daily = DATA[deck].daily;
  if (!daily.length) return emptyOption("no answers yet");
  const days = [];
  const byDay = new Map(daily.map((d) => [d.d, d]));
  for (let time = Date.parse(`${daily[0].d}T00:00:00Z`);
       time <= Date.parse(`${daily[daily.length - 1].d}T00:00:00Z`); time += DAY_MS) {
    const key = new Date(time).toISOString().slice(0, 10);
    days.push(byDay.get(key) ?? { d: key, new: 0, learn: 0, review: 0, minutes: 0 });
  }
  return {
    tooltip: tooltip({ trigger: "axis", axisPointer: { type: "shadow" } }),
    legend: legend(),
    grid: grid({ top: 46 }),
    xAxis: categoryAxis(days.map((d) => shortDate(d.d))),
    yAxis: [
      valueAxis({ name: "answers" }),
      valueAxis({ name: "minutes", position: "right", splitLine: { show: false } }),
    ],
    series: [
      bar("First time seen", days.map((d) => d.new), PALETTE.new),
      bar("Learning steps", days.map((d) => d.learn), PALETTE.learning),
      bar("Scheduled reviews", days.map((d) => d.review), PALETTE.mature),
      line("Minutes", days.map((d) => d.minutes), PALETTE.violet,
           { yAxisIndex: 1, lineStyle: { width: 2, color: PALETTE.violet } }),
    ],
  };
}

function cumulativeOption(deck) {
  const daily = DATA[deck].daily;
  if (!daily.length) return emptyOption("no answers yet");
  const steps = Math.max(1, Math.ceil(daily.length / 260));
  const rows = daily.filter((_, index) => index % steps === 0 || index === daily.length - 1);
  return {
    tooltip: tooltip({ trigger: "axis" }),
    legend: legend(),
    grid: grid({ top: 46 }),
    xAxis: categoryAxis(rows.map((d) => shortDate(d.d)), { boundaryGap: false }),
    yAxis: [
      valueAxis({ name: "cards" }),
      valueAxis({ name: "answers", position: "right", splitLine: { show: false } }),
    ],
    series: [
      line("Cards seen", rows.map((d) => d.cards_started), PALETTE.accent,
           { areaStyle: { opacity: 0.16 } }),
      line("Answers given", rows.map((d) => d.reviews_total), PALETTE.violet,
           { yAxisIndex: 1, lineStyle: { width: 2, color: PALETTE.violet } }),
    ],
  };
}

/* How many answers a card needed before it stopped being a learning step and became a
 * scheduled review. The plainest reading of "how fast do I learn". */
function graduationOption(deck) {
  const g = DATA[deck].graduation;
  if (!g.n) return emptyOption("no card has graduated yet");
  const keys = Object.keys(g.histogram);
  return {
    tooltip: tooltip({ trigger: "axis", axisPointer: { type: "shadow" },
      formatter: (points) => {
        const p = points[0];
        return `${p.name} ${p.name === "6+" ? "or more" : ""} answers before graduating<br>` +
               `${n(p.value)} cards (${pct(Math.round(100 * p.value / g.n))})`;
      } }),
    grid: grid({ top: 20 }),
    xAxis: categoryAxis(keys, { name: "answers", nameLocation: "middle", nameGap: 26,
                                nameTextStyle: axisLabel() }),
    yAxis: valueAxis({ name: "cards" }),
    series: [bar("cards", keys.map((k) => g.histogram[k]), PALETTE.accent,
                 { label: { show: true, position: "top", color: MUTED, fontSize: 10 } })],
  };
}

/* The multiplier the scheduler is applying, against the interval it just tested. The
 * taper is the story: a card one day old jumps out to a week, a two-month-old card
 * barely moves. */
function intervalStepOption(deck) {
  const rows = DATA[deck].interval_step;
  if (!rows.length) return emptyOption("no scheduled review has happened yet");
  return {
    tooltip: tooltip({ trigger: "axis", axisPointer: { type: "shadow" },
      formatter: (points) => {
        const row = rows[points[0].dataIndex];
        return `Survived ${row.last}<br>` +
               `${n(row.asked)} reviews, ${pct(row.pass_rate)} passed<br>` +
               `next interval ~${row.median_next} days (×${row.median_factor})`;
      } }),
    legend: legend(),
    grid: grid({ top: 46 }),
    xAxis: categoryAxis(rows.map((r) => r.last), { name: "interval just tested",
                           nameLocation: "middle", nameGap: 26, nameTextStyle: axisLabel() }),
    yAxis: [
      valueAxis({ name: "days" }),
      valueAxis({ name: "×", position: "right", splitLine: { show: false } }),
    ],
    series: [
      bar("median next interval", rows.map((r) => r.median_next), PALETTE.accent,
          { label: { show: true, position: "top", color: MUTED, fontSize: 10,
                     formatter: "{c}d" } }),
      line("multiplier", rows.map((r) => r.median_factor), PALETTE.hard,
           { yAxisIndex: 1, symbol: "circle", showSymbol: true, symbolSize: 6,
             lineStyle: { width: 2, color: PALETTE.hard },
             label: { show: true, position: "top", color: PALETTE.hard, fontSize: 10,
                      formatter: "×{c}" } }),
    ],
  };
}

/* Does a word survive a month? The pass rate against how long the gap was, which is the
 * only chart here that answers whether the intervals are set right. */
function forgettingOption(deck) {
  const rows = DATA[deck].forgetting_curve;
  if (!rows.length) return emptyOption("no scheduled review has happened yet");
  return {
    tooltip: tooltip({ trigger: "axis", axisPointer: { type: "shadow" },
      formatter: (points) => {
        const row = rows[points[0].dataIndex];
        return `Left alone ${row.interval}<br>` +
               `${n(row.n)} reviews, ${pct(row.pass_rate)} passed<br>` +
               `${n(row.again)} pressed Again`;
      } }),
    legend: legend(),
    grid: grid({ top: 46 }),
    xAxis: categoryAxis(rows.map((r) => r.interval), { name: "gap before the answer",
                           nameLocation: "middle", nameGap: 26, nameTextStyle: axisLabel() }),
    yAxis: [
      valueAxis({ name: "% right", max: 100, axisLabel: axisLabel({ formatter: "{value}%" }) }),
      valueAxis({ name: "reviews", position: "right", splitLine: { show: false } }),
    ],
    series: [
      bar("still known", rows.map((r) => r.pass_rate), PALETTE.mature,
          { label: { show: true, position: "top", color: MUTED, fontSize: 10,
                     formatter: "{c}%" } }),
      line("reviews at this gap", rows.map((r) => r.n), PALETTE.accent,
           { yAxisIndex: 1, symbol: "circle", showSymbol: true, symbolSize: 5,
             lineStyle: { width: 1, color: PALETTE.accent, type: "dashed" } }),
    ],
  };
}

/* One shape for both donuts: no labels around the ring, because five of them do not fit
 * in a third of the page and ECharts answers that by hiding or cutting them. The count
 * goes in the middle and every slice is named with its number in the legend instead. */
function donutOption(rows, unit) {
  const total = rows.reduce((sum, r) => sum + r.value, 0);
  const byName = Object.fromEntries(rows.map((r) => [r.name, r.value]));
  return {
    tooltip: tooltip({ trigger: "item",
      formatter: (p) => `${p.name}: ${n(p.value)} ${unit} (${p.percent}%)` }),
    title: {
      text: n(total), subtext: unit, left: "center", top: "33%", textAlign: "center",
      textStyle: { color: INK, fontSize: 21, fontWeight: 620 },
      subtextStyle: { color: MUTED, fontSize: 11 },
    },
    legend: legend({
      bottom: 0, top: undefined, itemWidth: 9, itemHeight: 9,
      textStyle: { color: MUTED, fontSize: 10 },
      formatter: (name) => `${name} ${n(byName[name])}`,
    }),
    series: [{
      type: "pie",
      radius: ["50%", "74%"],
      center: ["50%", "40%"],
      itemStyle: { borderColor: "#0b1120", borderWidth: 2 },
      label: { show: false },
      labelLine: { show: false },
      data: rows.map((r) => ({ name: r.name, value: r.value, itemStyle: { color: r.color } })),
    }],
  };
}

function buttonsOption(deck) {
  const buttons = DATA[deck].buttons;
  const rows = [
    { name: "Again", value: buttons.again, color: PALETTE.again },
    { name: "Hard", value: buttons.hard, color: PALETTE.hard },
    { name: "Good", value: buttons.good, color: PALETTE.good },
    { name: "Easy", value: buttons.easy, color: PALETTE.easy },
  ].filter((r) => r.value > 0);
  if (!rows.length) return emptyOption("no answers yet");
  return donutOption(rows, "answers");
}

function distributionOption(deck, key, color, name) {
  const table = DATA[deck].distributions[key];
  const labels = Object.keys(table);
  if (!labels.length || labels.every((l) => !table[l])) return emptyOption("nothing to show yet");
  return {
    tooltip: tooltip({ trigger: "axis", axisPointer: { type: "shadow" },
      formatter: (points) => `${name} ${points[0].name}: ${n(points[0].value)} cards` }),
    grid: grid({ top: 20 }),
    xAxis: categoryAxis(labels, { name, nameLocation: "middle", nameGap: 26,
                                  nameTextStyle: axisLabel(),
                                  axisLabel: axisLabel({ rotate: labels.length > 8 ? 30 : 0 }) }),
    yAxis: valueAxis({ name: "cards" }),
    series: [bar(name, labels.map((l) => table[l]), color,
                 { label: { show: true, position: "top", color: MUTED, fontSize: 10,
                            formatter: (p) => (p.value ? n(p.value) : "") } })],
  };
}

function standingOption(deck) {
  const standing = DATA[deck].summary.standing;
  const rows = [
    { name: "New", value: standing.new, color: PALETTE.new },
    { name: "Learning", value: standing.learning, color: PALETTE.learning },
    { name: "Young", value: standing.young, color: PALETTE.young },
    { name: "Mature", value: standing.mature, color: PALETTE.mature },
    { name: "Suspended", value: standing.suspended, color: PALETTE.suspended },
  ].filter((r) => r.value > 0);
  if (!rows.length) return emptyOption("no cards yet");
  return donutOption(rows, "cards");
}

/* A week at a time: how much stuck, and how long an answer took. A pass rate that falls
 * while the median answer time rises is the ordinary sign of a deck getting harder. */
function weeklyOption(deck) {
  const rows = DATA[deck].weekly;
  if (!rows.length) return emptyOption("no answers yet");
  return {
    tooltip: tooltip({ trigger: "axis",
      formatter: (points) => {
        const row = rows[points[0].dataIndex];
        return `Week of ${monthDay(row.week)}<br>${n(row.n)} answers<br>` +
               `${pct(row.pass_rate)} right, median ${secs(row.median_seconds)}<br>` +
               `${row.minutes} minutes`;
      } }),
    legend: legend(),
    grid: grid({ top: 46 }),
    xAxis: categoryAxis(rows.map((r) => monthDay(r.week)), { boundaryGap: true,
                           axisLabel: axisLabel({ rotate: rows.length > 8 ? 40 : 0,
                                                  formatter: (v) => v.split(" ")[0] + " " +
                                                                    v.split(" ")[1] }) }),
    yAxis: [
      valueAxis({ name: "% right", max: 100, axisLabel: axisLabel({ formatter: "{value}%" }) }),
      valueAxis({ name: "minutes", position: "right", splitLine: { show: false } }),
    ],
    series: [
      bar("minutes studied", rows.map((r) => r.minutes), "rgba(96,165,250,.55)",
          { yAxisIndex: 1, borderRadius: [3, 3, 0, 0] }),
      line("still known", rows.map((r) => r.pass_rate), PALETTE.mature,
           { symbol: "circle", showSymbol: true, symbolSize: 5,
             lineStyle: { width: 2, color: PALETTE.mature } }),
    ],
  };
}

/* What is waiting, day by day, taken from the cards' own due dates. A wall a fortnight
 * out is worth seeing before it arrives. */
function forecastOption(deck) {
  const rows = DATA[deck].forecast;
  if (!rows.length) return emptyOption("no card is scheduled yet");
  return {
    tooltip: tooltip({ trigger: "axis", axisPointer: { type: "shadow" },
      formatter: (points) => {
        const row = rows[points[0].dataIndex];
        return `${row.date} (+${row.offset} days)<br>${n(row.cards)} cards waiting`;
      } }),
    grid: grid({ top: 20 }),
    xAxis: categoryAxis(rows.map((r) => shortDate(r.date)),
                        { axisLabel: axisLabel({ interval: 2 }) }),
    yAxis: valueAxis({ name: "cards" }),
    series: [bar("cards due", rows.map((r) => r.cards), PALETTE.accent)],
  };
}

/* When the studying happens, on the clock rather than on Anki's 4am day boundary - the
 * point of this one is the wall clock. */
function clockOption(deck) {
  const grid_data = DATA[deck].hour_weekday;
  const values = [];
  let most = 0;
  grid_data.grid.forEach((row, weekday) => row.forEach((minutes, hour) => {
    values.push([hour, weekday, minutes]);
    most = Math.max(most, minutes);
  }));
  return {
    tooltip: tooltip({ formatter: (p) => `${grid_data.weekdays[p.value[1]]} at ` +
      `${String(p.value[0]).padStart(2, "0")}:00 — ${p.value[2]} minutes` }),
    grid: grid({ top: 12, left: 42, bottom: 26, right: 12 }),
    xAxis: categoryAxis([...Array(24).keys()].map((h) => String(h).padStart(2, "0")),
                        { splitArea: { show: true }, axisLine: { show: false } }),
    // `inverse` puts Monday at the top, the way a calendar is read.
    yAxis: categoryAxis(grid_data.weekdays, { splitArea: { show: true }, inverse: true }),
    visualMap: {
      min: 0, max: Math.max(1, Math.round(most)), calculable: true, orient: "horizontal",
      left: "center", bottom: -8, itemWidth: 12, itemHeight: 90,
      textStyle: { color: MUTED, fontSize: 10 },
      inRange: { color: ["#0f172a", "#1e3a8a", "#3b82f6", "#22d3ee", "#fbbf24"] },
    },
    series: [{
      type: "heatmap",
      data: values,
      itemStyle: { borderColor: "rgba(8,12,22,.6)", borderWidth: 1 },
      emphasis: { itemStyle: { borderColor: INK, borderWidth: 1 } },
    }],
  };
}

/* The habit, as a calendar: one square per day, darker for more answers. */
function calendarOption(deck) {
  const rows = DATA[deck].days;
  if (!rows.length) return emptyOption("no answers yet");
  const most = Math.max(...rows.map((r) => r.reviews));
  return {
    tooltip: tooltip({ formatter: (p) => `${p.value[0]}: ${n(p.value[1])} answers` }),
    visualMap: {
      min: 0, max: most, orient: "horizontal", left: "center", bottom: -4,
      itemWidth: 12, itemHeight: 90, textStyle: { color: MUTED, fontSize: 10 },
      inRange: { color: ["#1e293b", "#1d4ed8", "#3b82f6", "#22d3ee", "#34d399"] },
    },
    calendar: {
      range: [rows[0].d, rows[rows.length - 1].d],
      cellSize: ["auto", 15],
      left: 40, right: 12, top: 24, bottom: 40,
      itemStyle: { color: "rgba(148,163,184,.08)", borderColor: "rgba(8,12,22,.6)" },
      splitLine: { lineStyle: { color: "rgba(148,163,184,.25)" } },
      dayLabel: { color: MUTED, fontSize: 10, nameMap: "en" },
      monthLabel: { color: MUTED, fontSize: 10, nameMap: "en" },
      yearLabel: { show: false },
    },
    series: [{
      type: "heatmap",
      coordinateSystem: "calendar",
      data: rows.map((r) => [r.d, r.reviews]),
    }],
  };
}

/* Two books, chapter by chapter. Each book numbers its own chapters, so this is only
 * meaningful for one book at a time: on "all decks" the same chapter number would mean
 * two different chapters added together, which is worse than showing nothing. */
function chaptersOption(deck) {
  const rows = DATA[deck].chapters;
  if (!rows.length || deck === "all") return null;
  return {
    tooltip: tooltip({ trigger: "axis", axisPointer: { type: "shadow" },
      formatter: (points) => {
        const row = rows[points[0].dataIndex];
        return `${row.chapter}: ${n(row.cards)} cards<br>` +
               `${n(row.mature)} mature, ${n(row.learning)} not yet<br>` +
               `median interval ${row.median_interval} days`;
      } }),
    legend: legend(),
    grid: grid({ top: 46, bottom: 10 }),
    xAxis: categoryAxis(rows.map((r) => r.chapter.replace("Chapter ", "ch")),
                        { axisLabel: axisLabel({ rotate: rows.length > 14 ? 40 : 0 }) }),
    yAxis: valueAxis({ name: "cards" }),
    series: [
      bar("Mature", rows.map((r) => r.mature), PALETTE.mature, { stack: "cards" }),
      bar("Young", rows.map((r) => Math.max(0, r.cards - r.mature - r.learning)), PALETTE.young,
          { stack: "cards", borderRadius: [3, 3, 0, 0] }),
      bar("Not yet", rows.map((r) => r.learning), PALETTE.new,
          { stack: "cards", borderRadius: [3, 3, 0, 0] }),
    ],
  };
}

/* How much of the studying happens at night, by minutes rather than answers - a 1am
 * session is usually a long one, and the share is worth stating plainly. */
function lateShare(deck) {
  const rows = DATA[deck].hour_weekday.grid;
  const total = rows.reduce((sum, row) => sum + row.reduce((a, b) => a + b, 0), 0);
  const late = rows.reduce((sum, row) => sum + row[22] + row[23] + row[0] + row[1], 0);
  return total ? Math.round(100 * late / total) : 0;
}

function emptyOption(message) {
  return {
    title: { text: message, left: "center", top: "middle",
             textStyle: { color: MUTED, fontSize: 13, fontWeight: "normal" } },
  };
}

/* Each definition becomes one card on the page. The `why` line says what the chart is
 * for, because a dashboard of unlabelled lines is a puzzle rather than a report. */
function chartDefs(deck) {
  const defs = [
    { id: "growth", span: 6, height: 300, title: "Words that are sticking",
      why: () => "The log replayed week by week: how many cards were still three weeks out at the time, not just how many were started. The violet line is the share that is mature.",
      option: () => growthOption(deck) },
    { id: "standing", span: 3, height: 300, title: "Where the cards stand now",
      why: "Anki's own stages. Suspended cards are held out of the rotation.",
      option: () => standingOption(deck) },
    { id: "buttons", span: 3, height: 300, title: "Which button gets pressed",
      why: "Good is most of it. Every Again here is a word that did not come back.",
      option: () => buttonsOption(deck) },
    { id: "volume", span: 8, height: 300, title: "What a study day looks like",
      why: "Answers split into first-time cards, learning steps and scheduled reviews, with the minutes on top. Days with nothing are kept as gaps.",
      option: () => volumeOption(deck) },
    { id: "weekly", span: 4, height: 300, title: "Week by week: how much stuck",
      why: "Pass rate against minutes. A pass rate falling while the minutes rise is a deck getting harder.",
      option: () => weeklyOption(deck) },
    { id: "intervalstep", span: 6, height: 300, title: "How far the scheduler pushes you",
      why: () => `What interval a card is given next, against the one it just survived. A card one day old jumps to about ${DATA[deck].interval_step[0]?.median_next ?? "—"} days.`,
      option: () => intervalStepOption(deck) },
    { id: "forgetting", span: 6, height: 300, title: "Does a word survive a month?",
      why: "Pass rate against how long the card had been left alone. A flat line at the far right means the intervals are set about right.",
      option: () => forgettingOption(deck) },
    { id: "graduation", span: 4, height: 280, title: "Answers needed to graduate",
      why: () => `How many answers a card took before it stopped being a learning step. Median ${DATA[deck].graduation.median || "—"} answers over ${DATA[deck].graduation.median_days || "—"} days.`,
      option: () => graduationOption(deck) },
    { id: "intervalnow", span: 4, height: 280, title: "How far out the cards sit",
      why: "The interval each card has been given, right now. A pile in the far buckets is a deck that is genuinely learned.",
      option: () => distributionOption(deck, "interval", PALETTE.accent, "current interval") },
    { id: "answertime", span: 4, height: 280, title: "How long an answer takes",
      why: "Anki stops its own timer at one minute, so the last bucket is a floor rather than a measurement.",
      option: () => distributionOption(deck, "answer_time", PALETTE.violet, "time on the answer") },
    { id: "lapses", span: 4, height: 280, title: "How often a card slips",
      why: "Lapses per card. Most cards never slip; the few that keep doing it are the ones worth rewriting.",
      option: () => distributionOption(deck, "lapses", PALETTE.again, "lapses") },
    { id: "forecast", span: 8, height: 280, title: "What is waiting in the next 30 days",
      why: "Taken from the due date Anki has already written on each card, so it is the real queue rather than an estimate.",
      option: () => forecastOption(deck) },
    { id: "calendar", span: 6, height: 340, title: "The habit, day by day",
      why: "One square per day of study. Empty squares are days off, and the gaps are easier to see than in a line.",
      option: () => calendarOption(deck) },
    { id: "clock", span: 6, height: 340, title: "When the studying happens",
      why: () => `On the clock, not on Anki's 4am day boundary, because the point is the wall clock. ${lateShare(deck)}% of the minutes in this selection land between 22:00 and 02:00.`,
      option: () => clockOption(deck) },
    { id: "cumulative", span: 6, height: 280, title: "Cards seen and answers given",
      why: "Everything grows together except the answers, which flatten off as the cards get harder and come around less often.",
      option: () => cumulativeOption(deck) },
    { id: "chapters", span: 12, height: 280, title: "Chapter by chapter",
      why: "Shown only when a single book deck is selected: each book numbers its own chapters, so adding them together would be nonsense.",
      option: () => chaptersOption(deck) },
  ];
  return defs.filter((def) => def.option() !== null);
}

function drawCharts(deck) {
  live.forEach((chart) => chart.dispose());
  live = [];
  const host = document.getElementById("charts");
  host.innerHTML = chartDefs(deck).map((def) => `
    <div class="col-12 col-lg-${def.span}">
      <div class="chart-card">
        <h2>${def.title}</h2>
        <p class="why">${typeof def.why === "function" ? def.why() : def.why}</p>
        <div class="chart" id="chart-${def.id}" style="height:${def.height}px"></div>
      </div>
    </div>`).join("");
  chartDefs(deck).forEach((def) => {
    const chart = echarts.init(document.getElementById(`chart-${def.id}`), null, { renderer: "canvas" });
    chart.setOption(def.option());
    live.push(chart);
  });
}

/* ---------- the tables ---------- */

function table(columns, rows, why, title, span = 4) {
  return `
    <div class="col-12 col-lg-${span}">
      <div class="table-wrap">
        <h2>${title}</h2>
        <p class="why">${why}</p>
        <div class="table-responsive">
          <table class="table table-sm align-middle">
            <thead><tr>${columns.map((c) => `<th class="${c.right ? "right" : ""}">${c.label}</th>`).join("")}</tr></thead>
            <tbody>${rows.map((row) => `<tr>${columns.map((c) => `<td class="${c.right ? "right num" : ""}">${row[c.key] ?? ""}</td>`).join("")}</tr>`).join("")}</tbody>
          </table>
        </div>
      </div>
    </div>`;
}

function drawTables(deck) {
  const showDeck = deck === "all";
  const deckColumns = showDeck ? [{ key: "deck", label: "deck" }] : [];
  const decks = DECKS.map((d) => d.id);
  const comparison = decks.map((id) => {
    const s = DATA[id].summary;
    return {
      deck: id === "all" ? "all five" : id,
      cards: n(s.cards),
      answers: n(s.answers),
      hours: `${s.hours}h`,
      median: secs(s.median_seconds),
      pass: pct(s.pass_rate),
      mature: pct(s.mature_pct),
      graduate: DATA[id].graduation.n ? n(DATA[id].graduation.median) : "—",
      streak: `${DATA[id].streaks.current} / ${DATA[id].streaks.longest}`,
    };
  });
  const wordRows = (source) => source.map((r) => ({
    ...r,
    lapses: n(r.lapses),
    answers: n(r.answers ?? r.reps),
    interval: `${r.interval}d`,
    ease: pct(r.ease),
  }));

  document.getElementById("tables").innerHTML = `<div class="row g-4">
    ${table([
      { key: "deck", label: "deck" }, { key: "cards", label: "cards", right: true },
      { key: "answers", label: "answers", right: true }, { key: "hours", label: "hours", right: true },
      { key: "median", label: "median", right: true }, { key: "pass", label: "right", right: true },
      { key: "mature", label: "mature", right: true },
      { key: "graduate", label: "to grad.", right: true },
      { key: "streak", label: "streak now/best", right: true },
    ], comparison, "Each deck side by side. &ldquo;To grad.&rdquo; is the median number of answers before a card became a scheduled review.", "The five decks, compared", 12)}
    ${table([...deckColumns,
      { key: "label", label: "word" }, { key: "lapses", label: "lapses", right: true },
      { key: "answers", label: "answers", right: true }, { key: "interval", label: "now", right: true },
      { key: "ease", label: "ease", right: true },
    ], wordRows(DATA[deck].hardest), "Most lapses first: the words that keep coming back and are worth a better mnemonic.", "The words that will not stick", showDeck ? 6 : 12)}
    ${table([...deckColumns,
      { key: "label", label: "word" }, { key: "interval", label: "interval", right: true },
      { key: "ease", label: "ease", right: true }, { key: "answers", label: "answers", right: true },
    ], wordRows(DATA[deck].easiest), "Longest interval, never lapsed: the words that are safely known.", "The words that stuck", showDeck ? 6 : 12)}
  </div>`;
}

/* ---------- page ---------- */

function drawPicker() {
  document.getElementById("deck-picker").innerHTML = DECKS.map((d) => `
    <button data-deck="${d.id}" class="${d.id === selected ? "active" : ""}">
      ${d.label}<span class="n">${n(DATA[d.id].summary.cards)}</span></button>`).join("");
  document.querySelectorAll("#deck-picker button").forEach((button) => {
    button.addEventListener("click", () => {
      selected = button.dataset.deck;
      render();
    });
  });
}

function drawNotes() {
  document.getElementById("notes").innerHTML = `
    <p class="mb-1">Read from Anki on <strong>${DATA.generated}</strong>; the numbers here were
    built at <strong>${DATA.built}</strong>. Anki holds ${n(DATA.all.summary.cards)} Portuguese cards
    across five decks, and every answer ever given to them is in this page's data —
    ${n(DATA.all.summary.answers)} of them.</p>
    <p class="mb-1">A few decisions worth knowing when reading the charts: a study day starts at
    04:00, as Anki has it, so an answer at 1am counts towards the day before. Anki stops its own
    timer at one minute, so no answer looks longer than that. Suspended cards are counted in the
    standing but left out of the interval chart. Cramming and manual rescheduling rows are not
    answers and are excluded everywhere.</p>
    <p class="mb-0">To refresh: <code>python3 tools/pt_stats.py --pull &amp;&amp; python3 tools/pt_stats.py --build</code>,
    then reload — <code>python3 -m http.server 8899 --directory pt-stats</code> serves this folder.</p>`;
}

function render() {
  const deck = DATA[selected];
  drawPicker();
  drawTiles(selected);
  drawCharts(selected);
  drawTables(selected);
  document.getElementById("range").textContent =
    `${deck.summary.first_day} → ${deck.summary.last_day}, ${n(deck.summary.answers)} answers`;
}

function fail(message) {
  document.getElementById("error").classList.remove("d-none");
  document.getElementById("error-text").textContent = message;
}

fetch("data.json")
  .then((r) => { if (!r.ok) throw new Error(`data.json answered ${r.status}`); return r.json(); })
  .then((data) => {
    DATA = data;
    document.getElementById("generated").textContent = data.generated;
    document.getElementById("built").textContent = data.built;
    drawNotes();
    render();
    window.addEventListener("resize", () => live.forEach((chart) => chart.resize()));
  })
  .catch((error) => fail(String(error.message || error)));
