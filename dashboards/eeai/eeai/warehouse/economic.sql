-- One eligible response per person per cell. The pooled panel includes superforecasters.
WITH participants AS (
  SELECT target_variable_id, target_year, COALESCE(ai_scenario_id, 'unconditional') AS scenario, percentile, cohort, participant_id,
         IF(MIN(value) = MAX(value), MIN(value), ERROR('Conflicting participant responses')) AS value,
         IF(cohort = 'full_panel', 1, MAX(weight_within_group)) AS weight
  FROM `mart_eeai.forecast_quantile_standard`
  CROSS JOIN UNNEST(IF(project_participant_group_name = 'superforecaster',
                       ['full_panel', 'superforecaster'], ['full_panel'])) AS cohort
  WHERE policy_id IS NULL AND survey = 'final-survey-full' AND weight_within_group > 0
    AND value IS NOT NULL AND participant_id IS NOT NULL
    AND project_participant_group_name IN ('econ', 'ai_expert', 'general_public', 'superforecaster')
  GROUP BY target_variable_id, target_year, scenario, percentile, cohort, participant_id
), responses AS (
  SELECT *, COUNT(*) OVER (PARTITION BY target_variable_id, target_year, scenario, percentile, cohort) AS respondents FROM participants
)
SELECT target_variable_id, target_year, scenario, percentile, cohort, value, weight, COUNT(*) AS frequency,
       MAX(respondents) AS respondents, COUNT(*) OVER () AS extract_rows
FROM responses GROUP BY target_variable_id, target_year, scenario, percentile, cohort, value, weight
ORDER BY target_variable_id, target_year, scenario, percentile, cohort, value, weight
