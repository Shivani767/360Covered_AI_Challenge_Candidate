# AI Coverage Assistant - Evaluation Report

- Mode: **OFFLINE_DETERMINISTIC - NOT AN LLM**
- Cases run: **127**
- Passed: **127**
- Failed: **0**
- Errors: **0**

## Case results

| Case | Result | Duration (s) |
| --- | --- | --- |
| `adversarial.AdversarialQuestionTest.answer_always_returns_a_non_empty_string` | PASS | 0.0094 |
| `adversarial.AdversarialQuestionTest.everything_request_is_refused_safely` | PASS | 0.001 |
| `adversarial.AdversarialQuestionTest.injections_do_not_leak_the_prompt` | PASS | 0.0058 |
| `adversarial.AdversarialQuestionTest.injections_do_not_leak_unauthorized_plan_details` | PASS | 0.0058 |
| `adversarial.AdversarialQuestionTest.injections_do_not_trigger_universal_promise` | PASS | 0.0057 |
| `adversarial.MalformedStateTest.empty_state_does_not_crash` | PASS | 0.0002 |
| `adversarial.MalformedStateTest.garbage_state_does_not_crash` | PASS | 0.0004 |
| `adversarial.MalformedStateTest.none_state_does_not_crash` | PASS | 0.0001 |
| `adversarial.MalformedStateTest.selected_plan_not_visible_is_not_recommended` | PASS | 0.0002 |
| `adversarial.MalformedStateTest.unknown_plan_ids_are_not_offered` | PASS | 0.0001 |
| `adversarial.ProviderFailureTest.missing_credential_is_reported_honestly` | PASS | 0.0001 |
| `adversarial.ProviderFailureTest.provider_error_is_reported_honestly` | PASS | 0.0001 |
| `catalog.CatalogTest.all_plans_loaded` | PASS | 0.0 |
| `catalog.CatalogTest.benefits_present` | PASS | 0.0 |
| `catalog.CatalogTest.exclusionary_plan_is_broad` | PASS | 0.0 |
| `catalog.CatalogTest.option_facts` | PASS | 0.0 |
| `catalog.CatalogTest.ordered_ids_uses_catalog_comparison_order` | PASS | 0.0 |
| `catalog.CatalogTest.plus_inherits_base` | PASS | 0.0 |
| `catalog.CatalogTest.prices_and_deductibles_match_catalog` | PASS | 0.0 |
| `catalog.CatalogTest.unknown_plan_returns_empty_facts` | PASS | 0.0 |
| `catalog.CatalogTest.wrap_does_not_inherit_base` | PASS | 0.0 |
| `catalog.CatalogTest.wrap_explicitly_excludes_powertrain` | PASS | 0.0 |
| `guardrails.ComponentCoverageClaimTest.alias_based_covered_claim_is_allowed` | PASS | 0.0002 |
| `guardrails.ComponentCoverageClaimTest.alias_based_excluded_claim_is_rejected` | PASS | 0.0002 |
| `guardrails.ComponentCoverageClaimTest.alias_based_negative_is_allowed` | PASS | 0.0001 |
| `guardrails.ComponentCoverageClaimTest.claim_attributed_to_the_plan_that_covers_it_is_allowed` | PASS | 0.0002 |
| `guardrails.ComponentCoverageClaimTest.claim_attributed_to_the_wrong_plan_is_rejected` | PASS | 0.0002 |
| `guardrails.ComponentCoverageClaimTest.excluded_component_claim_by_plan_id_is_rejected` | PASS | 0.0001 |
| `guardrails.ComponentCoverageClaimTest.excluded_component_claim_is_rejected` | PASS | 0.0001 |
| `guardrails.ComponentCoverageClaimTest.exclusion_statement_is_allowed` | PASS | 0.0001 |
| `guardrails.ComponentCoverageClaimTest.list_of_covered_components_is_allowed` | PASS | 0.0004 |
| `guardrails.ComponentCoverageClaimTest.mixed_clauses_with_a_true_claim_are_allowed` | PASS | 0.0002 |
| `guardrails.ComponentCoverageClaimTest.mixed_clauses_with_one_false_claim_are_rejected` | PASS | 0.0002 |
| `guardrails.ComponentCoverageClaimTest.negative_statement_is_allowed` | PASS | 0.0001 |
| `guardrails.ComponentCoverageClaimTest.option_covered_component_is_not_a_violation` | PASS | 0.0002 |
| `guardrails.ComponentCoverageClaimTest.option_excluded_component_claim_is_rejected` | PASS | 0.0002 |
| `guardrails.ComponentCoverageClaimTest.shorter_plan_name_inside_longer_name_is_not_attribution` | PASS | 0.0002 |
| `guardrails.ComponentCoverageClaimTest.unpurchased_option_component_claim_is_rejected` | PASS | 0.0002 |
| `guardrails.GuardrailTest.authorized_plan_id_allowed` | PASS | 0.0001 |
| `guardrails.GuardrailTest.authorized_scope_lists_all_catalog_ids` | PASS | 0.0 |
| `guardrails.GuardrailTest.bumper_to_bumper_claim_rejected` | PASS | 0.0001 |
| `guardrails.GuardrailTest.claim_approval_rejected` | PASS | 0.0001 |
| `guardrails.GuardrailTest.conditional_benefit_allowed` | PASS | 0.0001 |
| `guardrails.GuardrailTest.correct_price_and_deductible_allowed` | PASS | 0.0001 |
| `guardrails.GuardrailTest.empty_answer_rejected` | PASS | 0.0001 |
| `guardrails.GuardrailTest.fabricated_deductible_rejected` | PASS | 0.0001 |
| `guardrails.GuardrailTest.fabricated_price_rejected` | PASS | 0.0001 |
| `guardrails.GuardrailTest.guaranteed_rental_rejected` | PASS | 0.0001 |
| `guardrails.GuardrailTest.purchased_option_coverage_allowed` | PASS | 0.0002 |
| `guardrails.GuardrailTest.shorter_plan_name_inside_longer_is_not_a_violation` | PASS | 0.0001 |
| `guardrails.GuardrailTest.unauthorized_plan_id_rejected` | PASS | 0.0001 |
| `guardrails.GuardrailTest.unauthorized_plan_name_rejected` | PASS | 0.0001 |
| `guardrails.GuardrailTest.universal_promise_is_rejected` | PASS | 0.0002 |
| `guardrails.GuardrailTest.unpurchased_option_coverage_rejected` | PASS | 0.0002 |
| `guardrails.GuardrailTest.unpurchased_option_with_hedge_allowed` | PASS | 0.0001 |
| `guardrails.MultiPlanAttributionAndMoneyTest.base_correct_price_and_deductible_allowed` | PASS | 0.0002 |
| `guardrails.MultiPlanAttributionAndMoneyTest.base_deductible_misattributed_is_rejected` | PASS | 0.0001 |
| `guardrails.MultiPlanAttributionAndMoneyTest.base_price_misattributed_to_plus_is_rejected` | PASS | 0.0001 |
| `guardrails.MultiPlanAttributionAndMoneyTest.engineer_is_not_the_engine_component` | PASS | 0.0001 |
| `guardrails.MultiPlanAttributionAndMoneyTest.multiplan_both_true_is_allowed` | PASS | 0.0002 |
| `guardrails.MultiPlanAttributionAndMoneyTest.multiplan_false_first_clause_is_rejected` | PASS | 0.0002 |
| `guardrails.MultiPlanAttributionAndMoneyTest.multiplan_wrap_engine_excluded_is_rejected` | PASS | 0.0002 |
| `guardrails.MultiPlanAttributionAndMoneyTest.screening_is_not_the_navigation_screen` | PASS | 0.0001 |
| `live_provider.LiveProviderTest.live_call_returns_model_answer` | PASS | 0.0073 |
| `live_provider.LiveProviderTest.live_request_carries_the_fact_pack` | PASS | 0.0006 |
| `live_provider.LiveProviderTest.missing_api_key_raises_clear_error` | PASS | 0.0 |
| `live_provider.LiveProviderTest.prompt_version_is_recorded_in_the_trace` | PASS | 0.0005 |
| `live_provider.LiveProviderTest.provider_error_is_surfaced_not_swallowed` | PASS | 0.0013 |
| `live_provider.LiveProviderTest.spend_cap_stops_further_calls` | PASS | 0.0003 |
| `live_provider.LiveProviderTest.unsafe_model_answer_is_caught_and_replaced` | PASS | 0.0009 |
| `live_provider.ProviderSelectionTest.anthropic_key_only_selects_anthropic` | PASS | 0.0001 |
| `live_provider.ProviderSelectionTest.base_url_selects_openai_compatible` | PASS | 0.0 |
| `live_provider.ProviderSelectionTest.explicit_provider_overrides_detection` | PASS | 0.0 |
| `live_provider.ProviderSelectionTest.missing_key_raises_clear_error` | PASS | 0.0 |
| `live_provider.ProviderSelectionTest.openai_key_only_selects_openai` | PASS | 0.0 |
| `multiturn.MultiTurnTest.conversation_does_not_drift_after_state_change` | PASS | 0.0017 |
| `multiturn.MultiTurnTest.history_is_bounded` | PASS | 0.0181 |
| `multiturn.MultiTurnTest.newly_visible_plan_can_be_discussed` | PASS | 0.0006 |
| `multiturn.MultiTurnTest.option_purchase_is_reflected` | PASS | 0.0009 |
| `multiturn.MultiTurnTest.option_removal_is_reflected` | PASS | 0.0009 |
| `multiturn.MultiTurnTest.plan_is_not_sticky_after_visibility_change` | PASS | 0.0015 |
| `multiturn.MultiTurnTest.reset_clears_referent_memory` | PASS | 0.0012 |
| `multiturn.MultiTurnTest.selection_change_is_reflected_on_next_turn` | PASS | 0.0008 |
| `provider_modes.GuardrailsAppliedToProvidersTest.exclusion_not_confused_with_coverage` | PASS | 0.0002 |
| `provider_modes.GuardrailsAppliedToProvidersTest.monetary_misattribution_rejected` | PASS | 0.0002 |
| `provider_modes.GuardrailsAppliedToProvidersTest.unpurchased_option_rejected` | PASS | 0.0002 |
| `provider_modes.GuardrailsAppliedToProvidersTest.unsupported_component_rejected` | PASS | 0.0002 |
| `provider_modes.MalformedOutputAndRepairTest.repair_succeeds` | PASS | 0.5037 |
| `provider_modes.MalformedOutputAndRepairTest.repair_then_fallback_metadata` | PASS | 0.5077 |
| `provider_modes.ProviderFailureTest.auth_failure_surfaces_clear_error` | PASS | 0.5062 |
| `provider_modes.ProviderFailureTest.timeout_surfaces_clear_error` | PASS | 0.0009 |
| `provider_modes.ProviderFailureTest.unavailable_endpoint_raises` | PASS | 0.0007 |
| `provider_modes.ProviderRequestConstructionTest.ollama_request_shape` | PASS | 0.0042 |
| `provider_modes.ProviderRequestConstructionTest.openai_request_shape` | PASS | 0.5027 |
| `provider_modes.ProviderSelectionTest.explicit_llm_provider_overrides_auto` | PASS | 0.0003 |
| `provider_modes.ProviderSelectionTest.offline_mode_uses_deterministic_provider` | PASS | 0.0001 |
| `provider_modes.ProviderSelectionTest.ollama_via_openai_compatible` | PASS | 0.0001 |
| `provider_modes.ProviderSelectionTest.ollama_without_api_key` | PASS | 0.0001 |
| `provider_modes.ProviderSelectionTest.openai_provider_from_key` | PASS | 0.0001 |
| `provider_modes.ProviderSelectionTest.openai_requires_api_key` | PASS | 0.0001 |
| `provider_modes.ResponseParsingTest.content_none_is_malformed` | PASS | 0.5051 |
| `provider_modes.ResponseParsingTest.empty_content_is_malformed` | PASS | 0.5051 |
| `provider_modes.ResponseParsingTest.ollama_response_parsing` | PASS | 0.5057 |
| `provider_modes.ResponseParsingTest.openai_response_parsing` | PASS | 0.5058 |
| `provider_modes.ResponseParsingTest.unexpected_shape_raises` | PASS | 0.5054 |
| `scenarios.ScenarioTest.all_scenarios_meet_expectation` | PASS | 0.0111 |
| `scenarios.ScenarioTraceTest.offline_mode_is_labelled_not_llm` | PASS | 0.0011 |
| `scenarios.ScenarioTraceTest.trace_records_authorization_scope` | PASS | 0.0022 |
| `smoke.Smoke.returns_text` | PASS | 0.0011 |
| `state.ReferentResolutionTest.explicit_plan_name_wins` | PASS | 0.0001 |
| `state.ReferentResolutionTest.longer_plan_name_wins` | PASS | 0.0 |
| `state.ReferentResolutionTest.named_but_unavailable_plan_is_not_resolved` | PASS | 0.0 |
| `state.ReferentResolutionTest.only_allowed_plan_is_used_as_last_resort` | PASS | 0.0 |
| `state.ReferentResolutionTest.option_id_matching` | PASS | 0.0 |
| `state.ReferentResolutionTest.recent_used_when_no_selection` | PASS | 0.0 |
| `state.ReferentResolutionTest.selection_wins_over_stale_recent` | PASS | 0.0 |
| `state.ReferentResolutionTest.shorter_plan_name_still_matches` | PASS | 0.0 |
| `state.StateNormalizationTest.allowed_is_intersection_not_union` | PASS | 0.0 |
| `state.StateNormalizationTest.empty_eligible_list_is_handled` | PASS | 0.0 |
| `state.StateNormalizationTest.malformed_state_does_not_raise` | PASS | 0.0 |
| `state.StateNormalizationTest.missing_eligible_ids_does_not_widen` | PASS | 0.0 |
| `state.StateNormalizationTest.missing_visible_ids_does_not_widen_to_whole_catalog` | PASS | 0.0 |
| `state.StateNormalizationTest.unknown_option_is_dropped` | PASS | 0.0 |
| `state.StateNormalizationTest.unknown_plan_ids_are_dropped_with_warning` | PASS | 0.0 |
| `sweep.SweepTest.every_answer_is_non_empty` | PASS | 0.0652 |
| `sweep.SweepTest.every_answer_mentions_no_blocked_plan_price` | PASS | 0.0458 |
| `sweep.SweepTest.no_safety_property_is_violated_anywhere` | PASS | 0.0466 |

## Example conversations

### C1: The 'give me everything' request

State: `{"eligible_ids": ["P-BASE", "P-PLUS", "P-EXCL"], "visible_ids": ["P-BASE", "P-PLUS"], "selected_id": "P-PLUS", "selected_options": []}`

**User:** Just give me the plan that covers everything.

**Assistant:** OFFLINE_DETERMINISTIC - NOT AN LLM

No. I am not able to describe any plan here as covering everything. Every plan in the catalog carries exclusions, so there is no blanket promise to be made. Exclusions that apply to the plans you can see include: pre-existing failures, normal maintenance items, damage caused by continued operation after malfunction. CoreDrive Plus covers: factory air-conditioning compressor, alternator, starter motor, factory-installed radiator, front suspension control arms, engine internal lubricated parts, transmission internal lubricated parts, drive axle internal parts. Optional coverage: you have not purchased any optional coverage. The optional items available on your plan are electronics_plus, exhaust_plus - they are offered, not in force, until purchased. Please note: repairs normally require prior authorization; maintenance documentation may be requested; final claims decision is made by the administrator.

### C2: Option offered but not purchased

State: `{"eligible_ids": ["P-PLUS"], "visible_ids": ["P-PLUS"], "selected_id": "P-PLUS", "selected_options": []}`

**User:** Is my navigation screen covered?

**Assistant:** OFFLINE_DETERMINISTIC - NOT AN LLM

factory-installed navigation screen would be covered by the electronics_plus option. That option is offered on your plan but has not been purchased, so factory-installed navigation screen is not currently covered. Optional coverage: you have not purchased any optional coverage. The optional items available on your plan are electronics_plus, exhaust_plus - they are offered, not in force, until purchased. Please note: repairs normally require prior authorization; maintenance documentation may be requested; final claims decision is made by the administrator.

### C3: Plan switch mid-conversation

State: `{"eligible_ids": ["P-BASE", "P-PLUS"], "visible_ids": ["P-BASE", "P-PLUS"], "selected_id": "P-BASE", "selected_options": []}`

**User:** Tell me about CoreDrive

**Assistant:** OFFLINE_DETERMINISTIC - NOT AN LLM

CoreDrive covers: engine internal lubricated parts, transmission internal lubricated parts, drive axle internal parts. CoreDrive (P-BASE) is $89 per month with a $200 deductible. Optional coverage: you have not purchased any optional coverage. The optional items available on your plan are electronics_plus, exhaust_plus - they are offered, not in force, until purchased.

**Event:** [selection changed to P-PLUS]

**User:** What is its deductible?

**Assistant:** OFFLINE_DETERMINISTIC - NOT AN LLM

The deductible for CoreDrive Plus (P-PLUS) is $100. Optional coverage: you have not purchased any optional coverage. The optional items available on your plan are electronics_plus, exhaust_plus - they are offered, not in force, until purchased.

## Limitations

- Offline mode is a deterministic rule-based adapter. It proves the authorization, grounding and guardrail behaviour, but it is **not** a language model and earns no credit for live model behaviour.
- Live mode requires a reviewer-supplied API key. The candidate had no provider credentials, so the live path was verified against a local mock HTTP server (see `tests/test_live_provider.py`) rather than a real provider round-trip.
- The catalog is synthetic and does not authorise any claim decision. Answers describe catalog wording only.
