# Graph 5 extension — November 24, 2026

Graph 5 adds 11 complete model panels (1,485 valid responses) to the original
32-model observational weather benchmark. Graph 6 is unchanged.

The version-3 instrument is unchanged: 27 pairs, five repetitions, 21 scored
pairs and six unscored probes. The forecast window is November 24–December 24,
2026. Scores use `redlines.views.observational.score_model`. All 33 pilot
responses were reviewed before the full run, under the user's delegated review.
Three output-capped attempts were retried with the original 32,000-token cap;
only complete, successfully parsed responses contribute to scores.

The added models have ECI above Opus 5 on the November 22 Epoch snapshot (also
verified identical to the November 24 download). Their ECI and scored aggregates
are in `web/demo/44-observational-extension.js`. Raw responses, provider usage,
validation records and the manifest remain in the private experiment archive.
The original model scores and pinned ECI values are retained. New calls use
direct provider REST APIs, vendor-default reasoning, and no tools, system prompt
or temperature override. Calendar windows, ECI vintages and API routing differ
between the two collections, so these are not controlled model comparisons.

The static benchmark extension ships with the frontend, separately from the
operational forecast snapshot. Normal deployment preserves all forecast blocks
and downloads. The display merges by model ID, avoiding duplication if a later
publication incorporates the extension. The published snapshot is never mutated.

Blue highlights models within the noise-ceiling band; other dots are gray.
The two summary statistics use neutral text colors: capability–skill
Spearman rho and the count of point estimates inside the existing noise-ceiling
band [0.887, 0.978]. The latter is descriptive, not a model-specific statistical
test. The merged chart has 43 models, nine in the band, and rho 0.8774.
