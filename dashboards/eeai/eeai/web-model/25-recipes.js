// How each headline outcome is computed from the forecast inputs: the
// equations (eeai/model/identities.py, written out), the steps for the
// diagram, and which inputs and intermediate series the detail card lists.
//
// A series id is an outcome or intermediate from the simulation summaries
// ("gdp_index", "sector_share") or a forecast input ("in." + symbol). The
// page's own data has the outcomes it draws; model-inputs.json (fetched when a
// card first opens) has the inputs and the other intermediates.

// Every series a card can show: label, symbol, unit, decimals, and per
// ("industry", "occupation" or "scalar"). input: a component the panel forecasts.
const SERIES = {
  "in.Q": { label: "Real value added", sym: "Q", unit: "index, 2025 = 1", decimals: 3, per: "industry", input: true },
  "in.P": { label: "Price of value added", sym: "P", unit: "index, 2025 = 1", decimals: 3, per: "industry", input: true },
  "in.pi": { label: "Labor productivity", sym: "π", unit: "index, 2025 = 1", decimals: 3, per: "industry", input: true },
  "in.h": { label: "Hours per employed person", sym: "h", unit: "hours per year", decimals: 0, per: "industry", input: true },
  "in.K": { label: "Capital input", sym: "K", unit: "index, 2025 = 1", decimals: 3, per: "industry", input: true },
  "in.lambda": { label: "Labor share", sym: "λ", unit: "%", decimals: 1, per: "industry", input: true },
  "in.u": { label: "Unemployment rate", sym: "u", unit: "%", decimals: 1, per: "occupation", input: true },
  "in.n": { label: "Unemployed with no occupation", sym: "n", unit: "% of the labor force", decimals: 2, per: "scalar", input: true },
  "in.Pop": { label: "Population 16 and over", sym: "Pop", unit: "millions", decimals: 1, per: "scalar", input: true },
  "in.C": { label: "Consumer prices (PCE)", sym: "C", unit: "index, 2025 = 1", decimals: 3, per: "scalar", input: true },
  "in.p10": { label: "10th percentile of weekly earnings", sym: "p₁₀", unit: "US$ per week, current", decimals: 0, per: "scalar", input: true },
  "in.p50": { label: "Median weekly earnings", sym: "p₅₀", unit: "US$ per week, current", decimals: 0, per: "scalar", input: true },
  "in.p90": { label: "90th percentile of weekly earnings", sym: "p₉₀", unit: "US$ per week, current", decimals: 0, per: "scalar", input: true },
  // The occupation mix: 484 shares a year, too many to list; it enters through employment by occupation.
  sigma: { label: "Occupation mix", sym: "σ", unit: "22 shares per industry", per: "cell", input: true },
  "in.E": { label: "Employment", sym: "E", unit: "millions", decimals: 2, per: "industry" },
  sector_growth: { label: "Real value added growth", unit: "% per year", decimals: 1, per: "industry" },
  sector_contribution: { label: "Contribution to GDP growth", unit: "pp", decimals: 2, per: "industry" },
  sector_share: { label: "Share of nominal GDP", sym: "w", unit: "%", decimals: 1, per: "industry" },
  occupation_employment: { label: "Employment", sym: "E", unit: "millions", decimals: 2, per: "occupation" },
  gdp_index: { label: "Real GDP", sym: "G", unit: "index, 2025 = 1", decimals: 3, per: "scalar" },
  nominal_gdp: { label: "Nominal GDP", sym: "N", unit: "US$ trillions", decimals: 2, per: "scalar" },
  hours: { label: "Hours worked", sym: "H", unit: "millions of hours", decimals: 0, per: "scalar" },
  employment: { label: "Employment", sym: "E", unit: "millions", decimals: 1, per: "scalar" },
  unemployed: { label: "Unemployed in an occupation group", sym: "U", unit: "millions", decimals: 2, per: "scalar" },
  labor_force: { label: "Labor force", sym: "L", unit: "millions", decimals: 1, per: "scalar" },
  tfp_index: { label: "TFP", sym: "A", unit: "index, 2025 = 1", decimals: 3, per: "scalar" },
  labor_share: { label: "Labor share", sym: "Λ", unit: "%", decimals: 1, per: "scalar" },
  pay_per_hour: { label: "Pay per hour", sym: "c", unit: "US$ per hour, current", decimals: 2, per: "scalar" },
  real_pay_index: { label: "Real pay per hour", sym: "R", unit: "index, 2025 = 1", decimals: 3, per: "scalar" },
  real_pay_lp: { label: "Labor productivity", sym: "LP", unit: "index, 2025 = 1", decimals: 3, per: "scalar" },
  real_pay_labor_share: { label: "Labor share, relative to 2025", sym: "Λ/Λ₂₀₂₅", unit: "ratio", decimals: 3, per: "scalar" },
  real_pay_price_gap: { label: "Price gap", sym: "D/C", unit: "ratio", decimals: 3, per: "scalar" },
};

// Growth over a gap: the annual rate (Δ is 1 to 2030, then 5).
const GROWTH = x => `g<sub>t</sub> =(${x}<sub>t</sub> / ${x}<sub>t−Δ</sub>)<sup>1/Δ</sup> − 1, where Δ is the years since the previous date (1 to 2030, then 5)`;
const EMPLOYMENT = "Employment by industry: E<sub>i,t</sub> = H<sub>i,2025</sub> · Q<sub>i,t</sub> / π<sub>i,t</sub> / h<sub>i,t</sub> (the hours the output needs, over hours per worker), and E<sub>t</sub> = Σ<sub>i</sub> E<sub>i,t</sub>";
const SHARES = "Each industry's nominal value added N<sub>i,t</sub> = N<sub>i,2025</sub> · Q<sub>i,t</sub> · P<sub>i,t</sub>, and its share w<sub>i,t</sub> = N<sub>i,t</sub> / Σ<sub>j</sub> N<sub>j,t</sub>";
const FISHER = "Real GDP, chained (Fisher): G<sub>t</sub> / G<sub>t−Δ</sub> = √( Σ<sub>i</sub> w<sub>i,t−Δ</sub> · Q<sub>i,t</sub> / Q<sub>i,t−Δ</sub>  ×  1 / Σ<sub>i</sub> w<sub>i,t</sub> · Q<sub>i,t−Δ</sub> / Q<sub>i,t</sub> )";
const HOURS = "Hours worked: H<sub>t</sub> = Σ<sub>i</sub> H<sub>i,2025</sub> · Q<sub>i,t</sub> / π<sub>i,t</sub>";
const LABOR_MARKET = [EMPLOYMENT,
  "Employment by occupation: E<sub>o,t</sub> = Σ<sub>i</sub> E<sub>i,t</sub> · σ<sub>io,t</sub> (each industry's 22 occupation shares rescaled to sum to 1)",
  "Unemployed: U<sub>t</sub> = Σ<sub>o</sub> E<sub>o,t</sub> · u<sub>o,t</sub> / (1 − u<sub>o,t</sub>)",
  "Labor force: L<sub>t</sub> = (E<sub>t</sub> + U<sub>t</sub>) / (1 − n<sub>t</sub>)"];
const SIGMA_NOTE = "The occupation mix σ (484 shares a year) is not listed; it enters through employment by occupation, shown below.";

// steps: the diagram's columns, left to right; the last is the outcome itself.
// industry / occupation / scalar: the series the Inputs view lists in each table.
const RECIPES = {
  gdp_growth: {
    text: "Each industry's real output, weighted by its share of nominal GDP and chained from date to date. An industry's contribution is its growth times its average share over the period.",
    eq: [SHARES, FISHER, GROWTH("G")],
    steps: [["in.Q", "in.P"], ["sector_share", "gdp_index"]],
    industry: ["in.Q", "in.P", "sector_share", "sector_growth", "sector_contribution"], scalar: ["gdp_index", "nominal_gdp"] },
  lp_growth: {
    text: "Real GDP per hour worked. Each industry's hours are the output it is forecast to produce divided by its forecast labor productivity.",
    eq: [HOURS, "Labor productivity: LP<sub>t</sub> = G<sub>t</sub> / (H<sub>t</sub> / H<sub>2025</sub>), with G real GDP, chained as in Real GDP growth", GROWTH("LP")],
    steps: [["in.Q", "in.P", "in.pi"], ["gdp_index", "hours"], ["real_pay_lp"]],
    industry: ["in.Q", "in.P", "in.pi", "sector_share"], scalar: ["gdp_index", "hours", "real_pay_lp"] },
  tfp_growth: {
    text: "Output growth not explained by more capital or more hours, industry by industry, weighted by the industries' average shares of nominal GDP.",
    eq: ["Each industry: Δln A<sub>i</sub> = Δln Q<sub>i</sub> − (1 − λ̄<sub>i</sub>) · Δln K<sub>i</sub> − λ̄<sub>i</sub> · Δln H<sub>i</sub>, with H<sub>i,t</sub> = H<sub>i,2025</sub> · Q<sub>i,t</sub> / π<sub>i,t</sub> and λ̄<sub>i</sub> the average labor share of the two dates",
      "The economy: Δln A = Σ<sub>i</sub> w̄<sub>i</sub> · Δln A<sub>i</sub>, with w̄<sub>i</sub> the average share of nominal GDP of the two dates",
      "growth<sub>t</sub> = exp(Δln A)<sup>1/Δ</sup> − 1"],
    steps: [["in.Q", "in.P", "in.pi", "in.K", "in.lambda"], ["sector_share", "hours"], ["tfp_index"]],
    industry: ["in.Q", "in.pi", "in.K", "in.lambda", "sector_share"], scalar: ["tfp_index", "hours"] },
  labor_share: {
    text: "Compensation as a share of national income: each industry's labor share, weighted by its share of nominal GDP.",
    eq: [SHARES, "Labor share: Λ<sub>t</sub> = Σ<sub>i</sub> w<sub>i,t</sub> · λ<sub>i,t</sub>"],
    steps: [["in.Q", "in.P", "in.lambda"], ["sector_share"]],
    industry: ["in.lambda", "sector_share", "in.Q", "in.P"], scalar: ["nominal_gdp"] },
  real_pay_growth: {
    text: "Compensation per hour, in consumer prices. It splits exactly into labor productivity, the labor share and the gap between the prices of what the economy produces and what households buy.",
    eq: ["Pay per hour: c<sub>t</sub> = Λ<sub>t</sub> · N<sub>t</sub> / H<sub>t</sub> (compensation over hours)",
      "Real pay, relative to 2025: R<sub>t</sub> = (c<sub>t</sub> / C<sub>t</sub>) / c<sub>2025</sub> = LP<sub>t</sub> × Λ<sub>t</sub> / Λ<sub>2025</sub> × D<sub>t</sub> / C<sub>t</sub>, with D the GDP price index, N<sub>t</sub> / (N<sub>2025</sub> · G<sub>t</sub>)",
      GROWTH("R")],
    steps: [["in.Q", "in.P", "in.pi", "in.lambda", "in.C"], ["real_pay_lp", "real_pay_labor_share", "real_pay_price_gap"], ["real_pay_index"]],
    industry: ["in.Q", "in.P", "in.pi", "in.lambda"], scalar: ["in.C", "pay_per_hour", "real_pay_lp", "real_pay_labor_share", "real_pay_price_gap", "real_pay_index"] },
  inflation_pce: {
    text: "Forecast directly: the panel gives the PCE price index for each year.",
    eq: ["inflation<sub>t</sub> = (C<sub>t</sub> / C<sub>t−Δ</sub>)<sup>1/Δ</sup> − 1"],
    steps: [["in.C"]], scalar: ["in.C"] },
  real_median_earnings: {
    text: "Median weekly earnings of full-time workers, in 2025 dollars.",
    eq: ["Real median earnings<sub>t</sub> = p<sub>50,t</sub> / C<sub>t</sub> (C is an index with 2025 = 1)"],
    steps: [["in.p50", "in.C"]], scalar: ["in.p50", "in.C"] },
  ratio_90_10: {
    text: "How far apart the top and bottom of full-time weekly earnings are.",
    eq: ["90/10 ratio<sub>t</sub> = p<sub>90,t</sub> / p<sub>10,t</sub>"],
    steps: [["in.p90", "in.p10"]], scalar: ["in.p90", "in.p10", "in.p50"] },
  employment: {
    text: "The hours each industry's forecast output needs, divided by the hours a worker in that industry works.",
    eq: [EMPLOYMENT],
    steps: [["in.Q", "in.pi", "in.h"], ["hours"]],
    industry: ["in.E", "in.Q", "in.pi", "in.h"], scalar: ["hours"] },
  epop: {
    text: "Employment as a share of the population 16 and over.",
    eq: [EMPLOYMENT, "Employment-to-population ratio = E<sub>t</sub> / Pop<sub>t</sub>"],
    steps: [["in.Q", "in.pi", "in.h", "in.Pop"], ["employment"]],
    industry: ["in.E", "in.Q", "in.pi", "in.h"], scalar: ["employment", "in.Pop"] },
  unemployment_rate: {
    text: "Employment comes from the industries; each occupation's forecast unemployment rate then sets how many are looking for work in that occupation.",
    eq: [...LABOR_MARKET, "Unemployment rate = 1 − E<sub>t</sub> / L<sub>t</sub>"], note: SIGMA_NOTE,
    steps: [["in.Q", "in.pi", "in.h", "sigma", "in.u", "in.n"], ["employment", "unemployed"], ["labor_force"]],
    industry: ["in.E", "in.h"], occupation: ["occupation_employment", "in.u"], scalar: ["employment", "unemployed", "in.n", "labor_force"] },
  lfpr: {
    text: "The labor force (the employed, plus the unemployed each occupation's rate implies) as a share of the population 16 and over.",
    eq: [...LABOR_MARKET, "Participation rate = L<sub>t</sub> / Pop<sub>t</sub>"], note: SIGMA_NOTE,
    steps: [["in.Q", "in.pi", "in.h", "sigma", "in.u", "in.n", "in.Pop"], ["employment", "unemployed"], ["labor_force"]],
    industry: ["in.E", "in.h"], occupation: ["occupation_employment", "in.u"], scalar: ["employment", "unemployed", "in.n", "labor_force", "in.Pop"] },
};

// The headline cards' one-line measures (the survey's headline cards carry one).
const MEASURES = {
  gdp_growth: "Annual rate; after 2030, averaged over each five years",
  unemployment_rate: "Share of the labor force without a job, annual average",
  lfpr: "Share of the population 16 and over in the labor force",
};
