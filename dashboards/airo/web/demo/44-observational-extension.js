// Public aggregate benchmark results; raw responses remain in the private run archive.
// See docs/graph5-extension.md for instrument and provenance.
const OBSERVATIONAL_EXTENSION = [
  {
    "id": "anthropic/claude-fable-5-2",
    "label": "Fable 5.2",
    "eci": 173.4,
    "eciSource": "epoch_capabilities_index_2026-11-22.csv",
    "responses": 135,
    "pairsScored": 21,
    "coherence": 0.00035000000000001696,
    "direction": {
      "k": 13,
      "n": 13,
      "p": 0.0001
    },
    "controlShift": 0.009000000000000008,
    "pass": true,
    "rho": 0.8852
  },
  {
    "id": "openai/gpt-6.2-astra",
    "label": "GPT-6.2 Astra",
    "eci": 172.82,
    "eciSource": "epoch_capabilities_index_2026-11-22.csv",
    "responses": 135,
    "pairsScored": 21,
    "coherence": 0.0,
    "direction": {
      "k": 13,
      "n": 13,
      "p": 0.0001
    },
    "controlShift": 0.0,
    "pass": true,
    "rho": 0.9091
  },
  {
    "id": "google/gemini-4-carbon",
    "label": "Gemini 4 Carbon",
    "eci": 169.68,
    "eciSource": "epoch_capabilities_index_2026-11-22.csv",
    "responses": 135,
    "pairsScored": 21,
    "coherence": 0.0,
    "direction": {
      "k": 13,
      "n": 13,
      "p": 0.0001
    },
    "controlShift": 0.0,
    "pass": true,
    "rho": 0.9173
  },
  {
    "id": "openai/gpt-6-astra",
    "label": "GPT-6 Astra",
    "eci": 169.21,
    "eciSource": "epoch_capabilities_index_2026-11-22.csv",
    "responses": 135,
    "pairsScored": 21,
    "coherence": 0.0,
    "direction": {
      "k": 13,
      "n": 13,
      "p": 0.0001
    },
    "controlShift": 0.0,
    "pass": true,
    "rho": 0.9206
  },
  {
    "id": "anthropic/claude-opus-5-5",
    "label": "Opus 5.5",
    "eci": 168.67,
    "eciSource": "epoch_capabilities_index_2026-11-22.csv",
    "responses": 135,
    "pairsScored": 21,
    "coherence": 0.0010000000000000009,
    "direction": {
      "k": 13,
      "n": 13,
      "p": 0.0001
    },
    "controlShift": 0.0049999999999999906,
    "pass": true,
    "rho": 0.8899
  },
  {
    "id": "openai/gpt-6.1-sol",
    "label": "GPT-6.1 Sol",
    "eci": 168.61,
    "eciSource": "epoch_capabilities_index_2026-11-22.csv",
    "responses": 135,
    "pairsScored": 21,
    "coherence": 0.0,
    "direction": {
      "k": 13,
      "n": 13,
      "p": 0.0001
    },
    "controlShift": 0.0,
    "pass": true,
    "rho": 0.9179
  },
  {
    "id": "openai/gpt-6.1-terra",
    "label": "GPT-6.1 Terra",
    "eci": 167.71,
    "eciSource": "epoch_capabilities_index_2026-11-22.csv",
    "responses": 135,
    "pairsScored": 21,
    "coherence": 0.0,
    "direction": {
      "k": 13,
      "n": 13,
      "p": 0.0001
    },
    "controlShift": 0.0,
    "pass": true,
    "rho": 0.9033
  },
  {
    "id": "anthropic/claude-fable-5-1",
    "label": "Fable 5.1",
    "eci": 167.06,
    "eciSource": "epoch_capabilities_index_2026-11-22.csv",
    "responses": 135,
    "pairsScored": 21,
    "coherence": 0.0010000000000000009,
    "direction": {
      "k": 13,
      "n": 13,
      "p": 0.0001
    },
    "controlShift": 0.007499999999999979,
    "pass": true,
    "rho": 0.872
  },
  {
    "id": "google/gemini-4-hydrogen",
    "label": "Gemini 4 Hydrogen",
    "eci": 166.81,
    "eciSource": "epoch_capabilities_index_2026-11-22.csv",
    "responses": 135,
    "pairsScored": 21,
    "coherence": 0.0,
    "direction": {
      "k": 13,
      "n": 13,
      "p": 0.0001
    },
    "controlShift": 0.0,
    "pass": true,
    "rho": 0.9049
  },
  {
    "id": "anthropic/claude-sonnet-5-5",
    "label": "Sonnet 5.5",
    "eci": 166.6,
    "eciSource": "epoch_capabilities_index_2026-11-22.csv",
    "responses": 135,
    "pairsScored": 21,
    "coherence": 0.0015000000000000013,
    "direction": {
      "k": 13,
      "n": 13,
      "p": 0.0001
    },
    "controlShift": 0.015000000000000013,
    "pass": true,
    "rho": 0.8791
  },
  {
    "id": "google/gemini-4-argon",
    "label": "Gemini 4 Argon",
    "eci": 166.53,
    "eciSource": "epoch_capabilities_index_2026-11-22.csv",
    "responses": 135,
    "pairsScored": 21,
    "coherence": 1.2999999999985246e-05,
    "direction": {
      "k": 13,
      "n": 13,
      "p": 0.0001
    },
    "controlShift": 0.0,
    "pass": true,
    "rho": 0.8915
  }
];

function observationalDisplayData(base) {
  if (!base) return null;
  const byId = new Map(base.models.map(m => [m.id, m]));
  // A later data publication may already contain these models.
  for (const model of OBSERVATIONAL_EXTENSION) {
    if (!byId.has(model.id)) byId.set(model.id, model);
  }
  const models = [...byId.values()].map(m => ({
    ...m, inPanel: false,
    color: m.rho >= base.noise.lo && m.rho <= base.noise.hi ? "#0969da" : "#91989f",
  })).sort((a, b) => a.eci - b.eci);
  const best = models.reduce((a, b) => b.rho > a.rho ? b : a);
  return {...base, models, best, nPass: models.filter(m => m.pass).length,
    nWithinNoise: models.filter(m => m.rho >= base.noise.lo && m.rho <= base.noise.hi).length};
}
