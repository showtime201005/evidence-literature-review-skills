"""Generate 100 varied, explicitly fictional ten-page-equivalent manuscripts.

Portable, deterministic, zero API calls.  The prose scaffold below is adapted
as static local text from the earlier generate_synthetic_benchmark.py fixture;
that private script is NOT imported or needed at runtime.  Parameters, designs,
cohorts, outcome patterns, resources, cases and late counterevidence are new.
This is a template-based engineering fixture, not 100 real scientific papers.
Optional raw token measurement uses only a caller-provided local tokenizer.
"""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import random
import re
from typing import Callable


GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20261020
DOMAINS = (
    ("museum object histories", "catalog record", "exhibition-date ambiguity", "catalogue age"),
    ("municipal eligibility notices", "versioned notice", "obsolete eligibility exception", "parallel policy changes"),
    ("tenant software support articles", "tenant article", "cross-tenant alias collision", "documentation maturity"),
    ("equipment assembly manuals", "manual section", "unit and warning-note separation", "manual length"),
    ("financial disclosure annotations", "disclosure note", "currency-scope substitution", "issuer reporting quality"),
    ("academic method summaries", "research abstract", "rare technical qualification loss", "specialty representation"),
    ("public-service policy bulletins", "policy bulletin", "post-update cache-miss burst", "seasonal question difficulty"),
    ("fabricated biomedical abstracts", "fabricated abstract", "adjacent-concept synonym substitution", "terminology ambiguity"),
    ("household maintenance guides", "maintenance procedure", "uncited transition between steps", "operator case selection"),
    ("municipal service rules", "service rule", "overconfidence near an answer boundary", "abstention-worthy question mix"),
    ("library archival finding aids", "archive entry", "collection versus item-level scope", "cataloguing completeness"),
    ("educational assessment rubrics", "rubric section", "grade-band boundary confusion", "curriculum revision timing"),
    ("transport timetable explanations", "service notice", "weekday and holiday conflation", "route complexity"),
    ("agricultural equipment catalogs", "equipment description", "model-year accessory mismatch", "product-family coverage"),
    ("environmental monitoring summaries", "monitoring note", "annual versus seasonal aggregation", "station representation"),
    ("fictional retail return policies", "return-policy clause", "regional exception omission", "regional demand mix"),
    ("laboratory inventory descriptions", "inventory record", "lot-specific storage qualifier loss", "inventory turnover"),
    ("digital preservation workflows", "workflow record", "checksum versus authenticity confusion", "format age"),
    ("university course catalogs", "course description", "prerequisite and co-requisite confusion", "course selection bias"),
    ("historical map annotations", "map annotation", "historical versus modern place-name mixing", "map-scale distribution"),
)
LANGUAGES = (("English",), ("English", "German"), ("Spanish",), ("Japanese",),
             ("French", "English"), ("Korean",), ("Portuguese",), ("Italian",),
             ("Swedish", "English"), ("Dutch",))
DESIGNS = (
    ("randomized query-level controlled experiment", True),
    ("cluster-randomized controlled experiment", True),
    ("randomized crossover experiment with balanced query order", True),
    ("randomized offline retrieval-pipeline experiment", True),
    ("randomized held-out calibration experiment", True),
    ("matched observational cohort study", False),
    ("observational before-and-after comparison", False),
    ("observational interrupted time-series study", False),
    ("observational deployment-log comparison", False),
)
FAMILIES = (
    (("Recall@10", "nDCG@10"), "higher", "query expansion", "single-pass dense retrieval",
     ("entity-scoped", "time-scoped", "tenant-scoped"), "answer faithfulness"),
    (("citation precision", "attribution coverage"), "higher", "citation-span alignment", "document-level source attachment",
     ("cross-language", "version-aware", "exception-aware"), "analyst review time"),
    (("answer F1", "factual consistency"), "higher", "evidence-window assembly", "fixed-length passage concatenation",
     ("table-aware", "unit-aware", "scope-aware"), "user satisfaction"),
    (("stale-answer rate", "wrong-version rate"), "lower", "cache invalidation", "fixed-time cache expiration",
     ("dependency-tracked", "effective-date-aware", "release-scoped"), "general answer quality"),
    (("Brier score", "calibration error"), "lower", "confidence calibration", "uncalibrated answer confidence",
     ("evidence-conditioned", "boundary-aware", "abstention-aware"), "infrastructure energy use"),
)
UPDATES = ("daily source releases", "weekly amendments and withdrawals", "monthly catalogue revisions",
           "quarterly manual revisions", "annual releases with interim corrections",
           "event-triggered corrections without a regular calendar")
SUBGROUPS = ("rare alias queries", "negated exception queries", "cross-language table queries",
            "queries immediately after updates", "long conditional queries", "near-boundary answer-switch queries")


__STATIC_PAGES__ = [('Research question and domain',
  ['This fictional study asks whether {mechanism} changes {metric} when a retrieval-augmented system '
   'processes {language} questions about {domain}. The question is deliberately narrow: it concerns '
   'evidence use within {dataset}, rather than the reliability of an unrestricted assistant. A record '
   'in this collection represents one {unit}; it is not a person, institution, or actual publication. '
   'The evaluation set contains {queries} questions and the frozen collection contains {documents} '
   'records. We examine a specific comparison with {comparator}, keeping the evidence budget at '
   '{budget}. The domain was chosen because {update} make document identity and validity relevant to '
   'retrieval. A useful system must identify supporting material, preserve its qualifications, and '
   'distinguish a missing observation from a negative result. Those requirements determine the analysis '
   'rather than an assumption that every pipeline change is beneficial.',
   'The motivating failure is {failure}. In this setting a superficially relevant passage can contain '
   'the correct words while referring to an incompatible object, version, or condition. The '
   'intervention therefore uses {safeguard} as a constraint on evidence selection. The constraint is '
   'intended to alter the available support, not to rewrite the underlying source statements. We '
   'separate the proposition that a candidate was retrieved from the stronger proposition that an '
   'answer is justified. This distinction matters for {metric}, whose operational definition addresses '
   'only the outcome specified in this paper. We do not substitute a favorable result on that outcome '
   'for measurements of every downstream property. In particular, {missing} was not measured, so '
   'conclusions about that property remain outside the observed evidence.',
   'The paper contributes a complete fictional evaluation protocol, an auditable comparison between two '
   'fixed pipelines, and a discussion of conditions under which the headline result fails to '
   'generalize. Its contribution is not a newly discovered empirical fact about real organizations. All '
   'scores, intervals, datasets, case descriptions, and resource measurements were authored as '
   'benchmark material. Within this controlled narrative, the important research distinction is between '
   'the primary aggregate and the prespecified subgroup of {subgroup}. The latter is retained even when '
   "it makes the overall interpretation less attractive. We also keep the collection's {stratum} "
   'visible in the analysis, because an aggregate can obscure who or what receives weaker evidence. The '
   'resulting report should state both the measured pattern and the uncertainty around it without '
   'converting either into a universal ranking.',
   'A working answer to the research question requires several connected observations. First, the '
   'source collection must be identifiable and frozen so that citations refer to the same text in both '
   'conditions. Second, the comparison needs an explicit unit of analysis and a consistent scoring '
   'rule. Third, the reader must know how {metric} behaves: for this metric, {direction} values are '
   'better under the definition used here. Finally, the evidence must preserve disconfirming cases '
   'rather than averaging them away. We evaluate those requirements in the context of {dataset} and its '
   '{language} material. A finding from this study is consequently conditional on that collection, the '
   'selected questions, the chosen evidence budget, and the implementation of {mechanism}. It is not '
   'evidence that unrelated languages, data sources, or outcome definitions behave similarly.']),
 ('Collection construction and update history',
  ['The {dataset} collection was constructed from fictional {domain}, with each {unit} assigned a '
   'stable local identifier. Authors generated internally consistent versions, including a small set of '
   'deliberate conflicts between a current statement and an older statement. The update schedule '
   'follows {update}. We retain both the text and its version relationship because deleting an older '
   'item would hide an important retrieval challenge. The frozen benchmark release includes {documents} '
   'records. Each record is associated with a domain label, a version marker, and a set of question '
   'links maintained in the annotation ledger. None of those identifiers denotes a real repository. '
   'Their purpose is to let a reviewer trace a claim to its exact synthetic context and distinguish a '
   'retrieval error from a change in the source material itself.',
   'Question construction begins with a desired information need rather than with a system-generated '
   'answer. Authors then write several surface forms that preserve the same need while varying lexical '
   'overlap with the source. For {language}, this includes appropriate spelling, morphology, and '
   'domain-specific expressions. Cases in {stratum} are represented explicitly instead of being merged '
   'into the dominant topic group. Questions that require information outside the frozen text are '
   'marked as unanswerable under the corpus-only policy. Those cases help distinguish warranted '
   'abstention from a failure to retrieve available evidence. The protocol does not allow external '
   'browsing to repair a difficult question. Otherwise the two pipelines could silently receive '
   'different evidence, and an apparent improvement could reflect access to an additional source rather '
   'than the specified retrieval intervention.',
   'The collection includes challenging but plausible distractors. A distractor shares an entity, '
   'label, or topic with the relevant {unit}, while differing in the condition that makes the answer '
   'applicable. Some distractors are obsolete after an update; others describe a neighboring case. The '
   'authors retain these distinctions in the source text so that an exact quotation can expose a scope '
   'error. The most important distractor family concerns {failure}. A robust extraction should report '
   'why the source does or does not apply, including qualifying words that are easy to omit in a '
   'compressed summary. A citation to a document title alone is insufficient for this purpose. The '
   'relevant evidence is the local statement together with its adjacent qualification, version note, or '
   'exception.',
   'Corpus preparation freezes the bytes before any pipeline is evaluated. The ledger records a content '
   'digest and the identifier of the relevant source location. Corrections after freezing create a new '
   'release rather than silently modifying the version already evaluated. This procedure makes a later '
   'replication possible without assuming that a live document has remained unchanged. It also exposes '
   'the limited scope of the benchmark: {dataset} represents authored text, not a sample of every '
   '{language} information service. Coverage of {stratum} does not guarantee coverage of every '
   'difficult case. We therefore report the composition and update process as study conditions. A '
   'secondary analysis may explore different collections, but it would answer an additional question '
   'and could not retroactively expand the scope of the present primary comparison.']),
 ('Study design and comparison',
  ['The study uses a {design}. The intervention condition implements {mechanism}; the reference '
   'condition implements {comparator}. Both conditions operate on the same frozen release of {dataset} '
   'and receive the same question definitions. The design determines which causal language is '
   'appropriate. {causal_statement} It remains necessary to specify what was actually changed, because '
   'even an assigned software intervention cannot establish the effects of an unmeasured organizational '
   'policy. We keep source access, question wording, and the scoring rubric fixed wherever the design '
   'permits. The comparison is evaluated at the level defined in the protocol rather than by selecting '
   'attractive examples after observing the output. This makes the aggregate result interpretable '
   'within the stated design while leaving its external validity open.',
   'Implementation order is logged so that a change in a cached resource does not masquerade as an '
   'intervention effect. Each run records the source release, retrieval configuration, relevant {unit} '
   'identifiers, and the allowed evidence budget of {budget}. When an answer cannot be grounded in the '
   'permitted material, the pipeline may abstain according to the shared rule. The decision to abstain '
   'is stored separately from the final outcome score. This distinction is needed because a cautious '
   'system can change the mix of attempted questions, and the score can become misleading if only '
   'successful attempts are retained. All eligible questions stay in the declared analysis set. '
   'Exclusions are defined by protocol violations such as corrupted source text, never by whether a '
   'pipeline happened to perform poorly on a case.',
   'The investigators identify {confound} as a material threat to interpretation. The handling of that '
   'threat follows the stated design and is not assumed to make every group exchangeable. We describe '
   'the observed context alongside the score difference so that a review can retain uncertainty about '
   'alternative explanations. The intervention also interacts with the question stratum: {subgroup} are '
   'not interchangeable with ordinary questions. The subgroup was specified before the scores were '
   'summarized, and its result is reported regardless of its direction. This avoids presenting an '
   'aggregate benefit as evidence of an improvement for each subset. The analysis should therefore '
   'distinguish the primary contrast, the subgroup contrast, and any illustrative cases used to explain '
   'the mechanism. They are related observations with different evidential roles.',
   'The protocol requires the two conditions to keep the same output policy and the same definition of '
   'a supported answer. A pipeline is not permitted to manufacture a source statement merely because it '
   'retrieves a more convenient record. The source text remains authoritative when it contradicts the '
   'generated answer. Investigators inspect examples containing a nearby {neighbor}, since a short '
   'excerpt can appear persuasive after the limiting sentence is removed. These inspections inform the '
   'error taxonomy, but they do not replace the full scoring set. A collection of favorable examples '
   'would not estimate {metric}. Conversely, a negative example can reveal a real failure mode without '
   'showing how common that failure is. We preserve both types of evidence and state which conclusions '
   'depend on aggregate scoring rather than on qualitative inspection.']),
 ('Pipeline and evidence handling',
  ['The reference pipeline begins with {comparator}. It constructs a candidate set from the frozen '
   'collection and applies a fixed selection policy before producing the evaluated output. The '
   'intervention replaces the relevant evidence-selection component with {mechanism}. Inputs and source '
   'releases are otherwise kept aligned within the constraints of the study design. Both conditions use '
   '{budget}, so an improvement cannot be explained merely by granting one condition an unlimited '
   'number of source passages. The intervention must work within that budget. Candidate provenance '
   'remains attached to every selected passage, allowing investigators to distinguish the passage that '
   'influenced an answer from an incidental item that happened to appear in the retrieval log. This '
   'separation matters when the correct document contains several incompatible local statements.',
   'Evidence assembly preserves the smallest complete context that can support or refute an answer. In '
   'particular, a quantitative value must remain connected to its unit, population, and relevant '
   'qualification. Where a table contains the relevant value, its caption and notes accompany the '
   'selected cells. A nearby {neighbor} is included when it changes applicability. This rule prevents a '
   'mechanically correct quotation from acquiring a broader meaning during summarization. The failure '
   'family of {failure} illustrates why this additional context is necessary. We do not treat quotation '
   'matching as sufficient proof of scientific support. It establishes that words appeared in the '
   'source, whereas the question of whether those words support the whole claim requires a separate '
   'contextual judgment.',
   'The intervention uses {safeguard} to narrow the interpretation of candidate evidence. That '
   'safeguard is configured before the held-out comparison and cannot be tuned separately on each '
   'failed evaluation question. Investigators document situations in which the safeguard removes a '
   'distractor and situations in which it suppresses useful evidence. The latter category is especially '
   'relevant for {subgroup}. A restrictive policy can improve average relevance while reducing recall '
   'for unusual language, rare concepts, or ambiguous identifiers. The protocol consequently records '
   'rejected candidates and the reason for rejection, rather than retaining only the final output. '
   "Those records permit a later analysis of whether the intervention's apparent benefit depends on a "
   'shift in the types of questions it is willing or able to answer.',
   'A trace consists of the question identifier, source release, candidate identities, selected '
   'evidence, output, and scoring decision. It is an auditable record of the fictional computation, not '
   'a transcript of private model reasoning. Investigators can replay the evidence selection from the '
   "frozen inputs without requiring access to an author's internal explanation. Repeated executions use "
   'seed {seed} where a deterministic ordering is required. A different seed may be explored in '
   'sensitivity analysis, but the declared result is not chosen from the most favorable execution. The '
   'trace also distinguishes a missing measurement from a measured zero. If a resource field is absent, '
   'no arithmetic can recover its value from the answer score alone. The source must report the '
   'measurement before a review can make a quantitative claim about it.']),
 ('Annotation and primary outcome',
  ['The primary endpoint is {metric}. Under the operational definition used for {dataset}, {direction} '
   'values indicate better performance. The score belongs to a defined evaluation task and should not '
   'be substituted for a different retrieval or answer-quality measure. In particular, ranking metrics '
   'depend on their cutoff and relevance judgments, while answer-level measures depend on how output '
   'claims are evaluated. A literature synthesis should preserve the metric name exactly, including a '
   'cutoff where present. Renaming every outcome as generic accuracy would remove information needed to '
   'judge comparability. We report the baseline score, intervention score, and '
   "intervention-minus-baseline contrast on the metric's native scale. These values are not relative "
   'percentage changes, and no unit conversion is implied by their decimal representation.',
   'Annotators inspect the relevant {unit} and its local context before assigning a label. Their task '
   "is to decide whether the requested information is supported under the source's stated conditions. "
   'They mark contradictory passages explicitly and do not resolve a conflict simply by choosing the '
   'sentence that matches the generated answer. For {language} questions, language-specific expressions '
   'are evaluated in context instead of being translated into an easier benchmark question. A '
   'disagreement record includes the competing interpretations and the source location needed to '
   'resolve them. Consensus labels are frozen before the compared output is summarized. This process '
   'reduces one source of outcome-dependent annotation, but it does not eliminate the limitations of an '
   'authored benchmark or establish that the rubric captures every dimension of practical usefulness.',
   'The scoring ledger contains all {queries} eligible questions. The score summary retains the '
   'distinction between overall performance and the prespecified subgroup of {subgroup}. Questions are '
   'not duplicated in the overall result simply because they appear in an explanatory case study. A '
   'single example may illustrate several error categories, but its evaluation weight follows the '
   'original analysis unit. This avoids inflating confidence by counting a rhetorically useful case '
   'multiple times. When the underlying design creates dependence between observations, uncertainty is '
   'computed at the corresponding grouping level. The paper reports uncertainty as a ninety-five '
   'percent confidence interval for the score contrast. An interval crossing zero is not described as '
   'proof of no effect; it indicates that the reported analysis does not clearly separate the contrast '
   'from zero.',
   'Annotation quality is examined through a structured review of disagreements, ambiguous question '
   'wording, and omitted source qualifications. The most consequential errors arise when a passage is '
   'relevant to the topic but supports a different version or condition. This concern links the rubric '
   'to {failure}. Investigators ask whether the output retained the decisive {neighbor}, whether it '
   'attributed the result to the correct source release, and whether it overstated what the evidence '
   'could establish. These checks are not additional favorable outcomes that may replace the '
   'prespecified primary endpoint. They explain the interpretation of {metric} and identify threats to '
   'validity. The missing measurement of {missing} remains missing after this exercise, since checking '
   'source support does not automatically measure every downstream outcome.']),
 ('Primary results and interval interpretation',
  ['The primary results are as follows. Baseline {metric} was {baseline}, and intervention {metric} was '
   '{intervention}. The intervention-minus-baseline difference was {delta}, with a ninety-five percent '
   'confidence interval from {ci_low} to {ci_high}. These numbers refer to the aggregate evaluation on '
   '{dataset}. They do not describe the subgroup, another dataset, or a different language. '
   "{primary_interpretation} The magnitude remains a contrast on the metric's native scale. We do not "
   'convert this contrast into a universal percentage improvement across retrieval systems. A review '
   'that reports only the direction while omitting the interval would lose information about precision. '
   'A review that changes the sign convention would also reverse the interpretation of outcomes for '
   'which lower values are preferable.',
   'Table 1 provides the principal numerical comparison in a form suitable for exact checking. The '
   'caption identifies the data release and the metric, and the notes define the contrast as '
   'intervention minus baseline. The subgroup row is included in the same table so that a reader cannot '
   'reasonably infer uniform benefit from the aggregate alone. Both rows are reported under the '
   'original protocol. The table does not contain a measurement of {missing}, nor can such a '
   'measurement be inferred from its score columns. Any source-based summary should retain the native '
   'metric, the contrast direction, the interval, and the target population of questions. A cell copied '
   'without the caption or notes could be numerically accurate yet semantically incomplete.',
   'A numerical contrast can be compatible with several mechanisms. In {dataset}, qualitative traces '
   'suggest that {mechanism} changes which {unit} is selected and how its qualifications survive '
   'evidence assembly. This pattern is consistent with the intended intervention, but the '
   'interpretation remains bounded by the {design}. {causal_caution} A plausible narrative does not '
   'repair a design limitation. We therefore separate the reported score change from a broader claim '
   'that the intervention is the sole cause of a practical improvement. The result also does not imply '
   'that {comparator} is universally inferior: the reference pipeline may behave differently under '
   'another corpus composition, update schedule, or evidence budget. Those counterfactual settings were '
   'not measured here.',
   'The numerical summary is deliberately accompanied by uncertainty rather than by a binary '
   'declaration of success. The confidence interval describes the precision of the specified contrast '
   'under the analysis assumptions. It does not certify that every question improved, that every rare '
   'case was protected, or that the system will maintain the same behavior after {update}. Nor does a '
   'favorable aggregate justify replacing the subgroup result with the overall average. The relevant '
   'scientific conclusion is conditional: this comparison estimates a particular difference in {metric} '
   'for the declared {language} collection and evaluation protocol. Claims about deployment utility '
   'would additionally require the missing measurement of {missing} and evidence about conditions '
   'beyond the present fictional corpus.']),
 ('Subgroup counterevidence and unexpected findings',
  ['The prespecified subgroup consists of {subgroup}. Its baseline {metric} was {subgroup_base}, and '
   'its intervention score was {subgroup_new}. The subgroup contrast was {subgroup_delta}, with a '
   'ninety-five percent confidence interval from {subgroup_low} to {subgroup_high}. '
   '{subgroup_interpretation} This observation must be retained beside the aggregate result. It is not '
   'an acceptable summary to state that every query benefited when this row is null or adverse. The '
   'subgroup also illustrates why a study can offer supporting evidence for a general mechanism while '
   'simultaneously providing counterevidence to a stronger, universal claim. The two observations are '
   'scientifically compatible when their scopes are stated explicitly.',
   'The unexpected finding was the persistence of {failure} despite the addition of {safeguard}. '
   'Investigators had expected this safeguard to resolve the relevant ambiguity more reliably. Traces '
   'showed that a structurally valid selection could still be wrong when the question depended on a '
   'distinction that the candidate representation did not preserve. The error was not simply a missing '
   'keyword. In some cases, the relevant evidence was present but lost a qualification during the '
   'passage-to-answer transition. This finding motivates a cautious interpretation of mechanism-based '
   'explanations: an intervention may address a known failure family while leaving a narrower variant '
   'unresolved. The study records this limitation instead of silently changing the definition of '
   'success after seeing the evaluation outputs.',
   'The subgroup analysis is not used to claim that an adverse pattern occurs in every underrepresented '
   'setting. Its scope is the declared set of {subgroup} in {dataset}. Other rare or difficult '
   'questions may involve different mechanisms. We keep that limitation explicit because an attractive '
   'synthesis can overgeneralize counterevidence just as easily as it can overgeneralize a benefit. A '
   'null interval is also not evidence that the intervention is harmless. It leaves uncertainty about '
   'effects of a size compatible with the reported interval. For a deployment decision, that '
   'uncertainty may be relevant even when the primary aggregate has a favorable direction. The present '
   'paper supplies the comparison and its bounds, rather than a universal rule for adopting or '
   'rejecting the intervention.',
   'Error inspection distinguishes source absence, candidate-selection failure, context loss, and '
   'unsupported answer formulation. The distinction matters because these categories suggest different '
   'remedies. If the corpus lacks a relevant statement, a more elaborate reranker cannot create valid '
   'evidence. If the relevant passage is retrieved but its {neighbor} is dropped, increasing retrieval '
   'recall may leave the central problem unchanged. If the output makes a claim that no selected '
   'passage supports, an exact source identifier does not rescue the claim. These observations '
   'contribute practical diagnostic structure without adding an unmeasured performance endpoint. In '
   'particular, they do not establish the missing outcome of {missing}. The most defensible synthesis '
   'preserves the unexpected failure and the boundary of the available measurements together.']),
 ('Resource accounting and unavailable measurements',
  ['Resource accounting is reported separately from {metric}. {cost_statement} Table 2 preserves this '
   'distinction between the score outcome and resource observations. The interpretation cannot be '
   'reversed by assuming that a compact pipeline is free or that an additional component must be '
   'expensive. Both assumptions would require measurements absent from the relevant source. Where a '
   'monetary value is reported, its unit is United States dollars per query under the fictional '
   'accounting boundary. It does not represent a total organizational budget, an estimate of staffing '
   "costs, or a claim about a live provider's price. The resource section consequently states the "
   'accounting boundary before discussing efficiency, and keeps unavailable fields explicitly '
   'unavailable.',
   'The measurement boundary determines what a resource number means. A per-query charge can include '
   'the components specified by the fictional logging protocol while excluding work performed outside '
   'the recorded request. A review should not extrapolate from such a value to lifetime cost without '
   'assumptions about query volume, maintenance, staffing, and changes in the source collection. The '
   'schedule of {update} is relevant because rebuilding evidence or invalidating a cache can move work '
   'between requests and maintenance periods. Our primary score does not measure that moved work. We '
   'therefore avoid converting the score difference into a cost-effectiveness ratio when its '
   'denominator is not adequately observed. A missing resource observation is an evidence gap that '
   'should remain visible in both the per-paper analysis and the integrated review.',
   'The study did not measure {missing}. This is an explicit limitation, not a statement that the '
   'corresponding quantity was zero, unchanged, or irrelevant. The absence also cannot be repaired by '
   'citing a different paper that evaluated a distinct outcome under another design. Such a citation '
   'might inform a broader discussion, but it would not make the present source contain a measurement '
   "it never reported. We treat this boundary as part of the study's scientific content. An extraction "
   'system should distinguish not reported from a null result supported by an interval. The subgroup '
   'contrast is an example of a reported uncertain or adverse result; the unavailable outcome is an '
   'example of information that was never obtained within the protocol.',
   'Efficiency claims require a joint description of resources, performance, and workload. For '
   '{dataset}, the workload consists of {queries} declared questions against {documents} frozen '
   'records, with {budget} supplied to the downstream stage. Those conditions should accompany any '
   'attempt to compare resource figures. A system serving a different language mix, a larger '
   'collection, or a more demanding evidence policy could have a different resource profile even if its '
   'score were similar. We report the observed accounting status and leave the unobserved components '
   'unresolved. This restraint is especially important in a synthetic benchmark: plausible numerical '
   'detail should never be mistaken for a measurement of an actual service. All resource values in this '
   'manuscript are fictional controlled facts for evaluating source-grounded review behavior.']),
 ('Validity, applicability, and reproducibility',
  ['Internal validity is bounded by the {design} and the way the authored collection represents '
   '{domain}. The principal named threat is {confound}. The paper describes that threat because it '
   'offers an alternative explanation or a boundary condition relevant to the observed contrast. A '
   'source-grounded review should not remove the threat when compressing the method into a short label. '
   'Nor should it infer that a particular adjustment makes all unobserved differences disappear. We '
   'preserve the exact design description and the distinction between the primary analysis and '
   'exploratory interpretation. The result remains evidence about the stated comparison, not a license '
   'to assert every causal pathway that could plausibly connect retrieval to a useful downstream '
   'decision.',
   'External validity requires caution because the collection, questions, and update process are all '
   'authored. The {language} material in {dataset} does not establish coverage of languages that were '
   'not evaluated. The presence of {stratum} in the benchmark also does not prove that the dataset '
   "represents every minority use case. The most relevant applicability conditions are the collection's "
   '{unit} structure, its update schedule, the evidence budget, and the use of {safeguard}. If any of '
   'those conditions changes, the proposed mechanism may interact differently with the input. We '
   'therefore report these conditions alongside the numerical result. They allow a later reader to '
   'assess similarity to a new task without pretending that a single fictional evaluation has already '
   'tested that task.',
   'Cross-paper numerical ranking is not justified by the information in this study alone. Recall, '
   'reciprocal rank, normalized discounted gain, answer F1, citation precision, factual consistency, '
   'freshness, attribution coverage, and calibration scores have different meanings and scales. Even '
   'two studies using the same label may apply different question populations or annotation policies. A '
   'review can compare methods and limitations across such studies, but it should not announce a '
   'winning system by sorting the raw score values. For {metric}, the declared favorable direction is '
   '{direction}; changing that direction would itself create an error. The appropriate comparison is '
   "between this paper's intervention and reference condition under {dataset}, with the uncertainty and "
   'subgroup evidence preserved.',
   'Reproducibility is supported by stable local identifiers, frozen source digests, deterministic '
   'generation seed {seed}, and a complete statement of the synthetic protocol. None of these features '
   'converts the study into a real publication. They make the benchmark internally auditable so that an '
   'extraction or verification system can be checked against known facts. A replication of the '
   'fictional evaluation should report whether it used the same corpus release and scoring definition '
   'before comparing its output. A literature-review benchmark should additionally record which parts '
   'of each source were read and which claims were ultimately cited. Coverage of every source part and '
   'support for every delivered claim are complementary obligations. Completing one does not '
   'automatically satisfy the other, and both should remain measurable in the resulting artifacts.']),
 ('Interpretation and bounded conclusions',
  ['The aggregate comparison estimates an intervention-minus-baseline difference of {delta} in '
   '{metric}, with a ninety-five percent confidence interval from {ci_low} to {ci_high}. That statement '
   'is the primary quantitative conclusion for {dataset}. Its interpretation is conditional on the '
   'declared {language} workload and the {design}. The subgroup of {subgroup} has a different contrast, '
   '{subgroup_delta}, with interval {subgroup_low} to {subgroup_high}. The two results should appear '
   'together in an evidence table. A summary that reports only the aggregate, or silently replaces the '
   'subgroup with the overall average, would erase relevant counterevidence. We consequently conclude '
   'with a bounded account of what was measured and where benefit, harm, or uncertainty does not '
   'support a stronger statement.',
   'The mechanism discussion identifies {mechanism} as a way to change evidence selection under '
   '{update}. The discussion also identifies {failure} as an unresolved or incompletely resolved '
   'challenge. These observations can motivate a new evaluation of the safeguard, but they do not '
   'establish that the problem has been solved. Further work should predefine a question set that '
   'isolates the suspected mechanism and preserve the local source context needed to judge errors. A '
   'future experiment could test whether a modified {safeguard} changes the subgroup result. It would '
   'need to report its own comparison rather than treating the present result as a forecast. The '
   'current manuscript neither supplies those future measurements nor fills the gap in {missing}.',
   'For a corpus-only literature review, the relevant synthesis should connect methods, evaluated '
   'outcomes, source conditions, counterevidence, resource status, and study limitations. It should '
   'make clear which statements are direct source facts and which are interpretations formed across '
   'studies. Direct facts from this manuscript include the score pair, confidence interval, subgroup '
   'result, design, language, and accounting status. An integrated interpretation may discuss recurring '
   'mechanisms, but its scope must follow the evidence actually available across the included papers. '
   'Unmeasured quantities should remain unknown, and observational comparisons should retain their '
   'causal limitations. This is particularly important when papers use different datasets or native '
   'metrics, since a smooth narrative can otherwise hide the conditions that make their results '
   'incomparable.',
   'In conclusion, {dataset} supplies a fictional, fully specified case for evaluating whether an '
   'automated review preserves scientific qualifications while handling a document of substantial '
   'length. The substantive content is distributed across the entire manuscript rather than '
   'concentrated only in an abstract. Methods, update conditions, endpoint definitions, adverse or null '
   'subgroup evidence, resource status, and validity limits all contribute to the final interpretation. '
   'The intended reading task therefore requires more than locating a headline score. It requires '
   'retaining the evidence needed to support a precise statement and rejecting stronger assertions that '
   'the source cannot justify. The manuscript is explicitly synthetic benchmark material, with no real '
   'authors, real dataset release, clinical recommendation, legal finding, or external publication '
   'claim.'])]


def decimal_text(value: Decimal, signed: bool = False) -> str:
    return format(value.quantize(Decimal("0.001")), "+.3f" if signed else ".3f")


def interval_kind(low: str, high: str, direction: str) -> str:
    lo, hi = Decimal(low), Decimal(high)
    if lo <= 0 <= hi:
        return "uncertain"
    return "benefit" if (lo > 0 if direction == "higher" else hi < 0) else "adverse"


def _contrast(rng: random.Random, direction: str, kind: str, *, subgroup=False) -> dict:
    baseline = Decimal(rng.randrange(420, 731) if direction == "higher" else rng.randrange(150, 301)) / 1000
    if kind == "uncertain":
        effect = Decimal(rng.choice((-7, -5, -3, 2, 4, 6))) / 1000
        half_width = Decimal(rng.randrange(16, 31)) / 1000
    else:
        magnitude = Decimal(rng.randrange(28, 62) if subgroup else rng.randrange(33, 86)) / 1000
        sign = 1 if direction == "higher" else -1
        effect = magnitude * (sign if kind == "benefit" else -sign)
        half_width = Decimal(rng.randrange(9, 23)) / 1000
    return {"baseline": decimal_text(baseline), "intervention": decimal_text(baseline + effect),
            "difference": decimal_text(effect, True), "ci_low": decimal_text(effect - half_width, True),
            "ci_high": decimal_text(effect + half_width, True), "interpretation": kind}


def build_studies(seed: int = DEFAULT_SEED) -> list[dict]:
    """100 distinct studies; 20 declared shared-panel pairs, hence 80 data groups."""
    studies = []
    for index in range(1, 101):
        family, domain_index = divmod(index - 1, 20)
        rng = random.Random(seed + index * 1009)
        metrics, direction, method, comparator, modifiers, missing = FAMILIES[family]
        domain, unit, failure, threat = DOMAINS[domain_index]
        design, randomized = DESIGNS[(index + 2 * family) % len(DESIGNS)]
        languages = list(LANGUAGES[(domain_index + 3 * family) % len(LANGUAGES)])
        if index == 1:
            languages = ["English"]
        elif index == 21:
            languages = ["English", "German"]
        language = " and ".join(languages)
        panel_rng = random.Random(seed + (domain_index + 1) * 7919)
        shared = family in (0, 1)
        group = "panel-D%02d" % (domain_index + 1) if shared else "independent-S%03d" % index
        queries = panel_rng.randrange(1300, 3501) if shared else rng.randrange(1200, 4101)
        documents = panel_rng.randrange(9000, 34001) if shared else rng.randrange(7000, 45001)
        primary_kind = ("benefit", "uncertain", "adverse", "benefit", "uncertain")[(domain_index + family) % 5]
        subgroup_kind = "adverse" if (index + family) % 3 == 0 else "uncertain"
        primary = _contrast(rng, direction, primary_kind)
        subgroup = _contrast(rng, direction, subgroup_kind, subgroup=True)
        cost_mode = index % 5
        base = Decimal(rng.randrange(6, 31)) / 1000
        newer = base + Decimal(rng.randrange(-3, 14)) / 1000
        cost_base = None if cost_mode in (0, 1) else decimal_text(base)
        cost_new = None if cost_mode in (0, 1, 2) else decimal_text(newer)
        if index % 17 == 0:
            cost_base, cost_new = "0.000", "0.004"
        cost_status = "not_measured" if cost_base is None and cost_new is None else "partially_reported" if None in (cost_base, cost_new) else "reported"
        mechanism = modifiers[(domain_index + family) % len(modifiers)] + " " + method
        code = "Case-%02d-%02d" % (domain_index + 1, family + 1)
        study = {"id": "S%03d" % index, "paper_id": "synthetic-S%03d" % index,
            "title": mechanism.capitalize() + " for " + domain,
            "languages": languages, "language": language, "domain": "fictional " + domain,
            "unit": unit, "dataset": "Collection-D%02d-F%02d-Sim" % (domain_index + 1, family + 1),
            "study_group_id": group, "shared_data": shared,
            "paired_study_id": ("S%03d" % (index + 20 if family == 0 else index - 20)) if shared else None,
            "release": "frozen-release-%02d-%02d" % (domain_index + 1, family + 1),
            "queries": queries, "documents": documents, "design": design, "randomized": randomized,
            "metric": metrics[domain_index % 2], "direction": direction, "primary": primary,
            "subgroup_name": SUBGROUPS[(index + family) % len(SUBGROUPS)], "subgroup": subgroup,
            "cost_baseline": cost_base, "cost_intervention": cost_new, "cost_status": cost_status,
            "cost_difference": decimal_text(Decimal(cost_new) - Decimal(cost_base), True) if cost_status == "reported" else None,
            "missing": missing, "mechanism": mechanism, "comparator": comparator,
            "update": UPDATES[(domain_index + family) % len(UPDATES)], "confound": threat,
            "failure": failure + " in " + code, "safeguard": "explicit " + modifiers[(domain_index + family) % len(modifiers)] + " qualification checks",
            "stratum": "sparsely represented " + unit + " categories", "budget": str(3 + (index * 7) % 10) + " supporting passages",
            "neighbor": "version-specific exception note", "case_code": code, "seed": seed + index * 1009,
            "late_failure": ("A conditionally negated exception in " + code + " was still converted into a positive answer after the final source-boundary check") if index >= 97 else None,
            "family": family, "domain_index": domain_index}
        studies.append(study)
    return studies


def _interpretation(row: dict, direction: str, name: str) -> str:
    kind = interval_kind(row["ci_low"], row["ci_high"], direction)
    if kind == "uncertain":
        return "The " + name + " interval includes zero; this analysis establishes neither a clear benefit nor absence of harm."
    if kind == "benefit":
        return "The " + name + " interval excludes zero in the favorable direction for this native endpoint."
    return "The " + name + " interval excludes zero in the adverse direction, indicating worse performance on this endpoint."


def derived(s: dict) -> dict:
    value = dict(s)
    for key in ("baseline", "intervention", "ci_low", "ci_high"):
        value[key] = s["primary"][key]
    value["delta"] = s["primary"]["difference"]
    for old, new in (("subgroup_base", "baseline"), ("subgroup_new", "intervention"),
                     ("subgroup_delta", "difference"), ("subgroup_low", "ci_low"), ("subgroup_high", "ci_high")):
        value[old] = s["subgroup"][new]
    value["subgroup"] = s["subgroup_name"]
    value["primary_interpretation"] = _interpretation(s["primary"], s["direction"], "primary")
    value["subgroup_interpretation"] = _interpretation(s["subgroup"], s["direction"], "subgroup")
    if s["randomized"]:
        value["causal_statement"] = "Assignment supports a narrow causal interpretation of this software contrast within the declared evaluation, not downstream real-world effects."
        value["causal_caution"] = "The assigned contrast does not establish the effect of an unmeasured deployment policy or an unrelated mechanism."
    else:
        value["causal_statement"] = "Exposure was not randomly assigned; the score difference is an association and must not be described as an established causal effect."
        value["causal_caution"] = "The nonrandom design permits residual confounding; matching or time adjustment does not establish that the intervention caused the difference."
    if s["cost_status"] == "not_measured":
        cost = "Monetary cost was not measured in either condition; both values and their difference are unknown, not zero."
    elif s["cost_status"] == "partially_reported":
        cost = "The fictional baseline monetary cost was USD " + s["cost_baseline"] + " per query; intervention cost was not measured, so neither a cost difference nor a cost ratio is available."
    else:
        cost = "The fictional baseline monetary cost was USD " + s["cost_baseline"] + " per query and intervention cost was USD " + s["cost_intervention"] + " per query; intervention minus baseline was " + s["cost_difference"] + " USD/query."
        if s["cost_baseline"] == "0.000":
            cost += " The zero baseline is an explicitly recorded fictional waived request charge, not a missing value or a claim that the organization has no expenses."
    value["cost_statement"] = cost + " These charges do not measure staffing effort, hardware ownership, or unlogged maintenance work."
    return value


def _tables(s: dict) -> tuple[str, str]:
    p, g = s["primary"], s["subgroup"]
    table1 = ("Table 1. Primary and prespecified subgroup outcomes for " + s["dataset"] + " using " + s["metric"] + ".\n\n"
        "| Evaluation set | Baseline | Intervention | Difference | 95% CI |\n| --- | --- | --- | --- | --- |\n"
        "| All eligible questions | {baseline} | {intervention} | {difference} | [{ci_low}, {ci_high}] |\n".format(**p) +
        ("| " + s["subgroup_name"] + " | {baseline} | {intervention} | {difference} | [{ci_low}, {ci_high}] |\n\n").format(**g) +
        "Table 1 notes. Difference is intervention minus baseline on the native score scale; " + s["direction"] + " is better. "
        "These 95% intervals describe contrasts, not separate means. Zero inside an interval is not proof of no effect or absence of harm.\n\n")
    costs = [x if x is not None else "not measured" for x in (s["cost_baseline"], s["cost_intervention"])]
    table2 = ("Table 2. Resource accounting for " + s["dataset"] + ".\n\n"
        "| Quantity | Baseline | Intervention | Interpretation boundary |\n| --- | --- | --- | --- |\n"
        "| Monetary cost, USD/query | " + costs[0] + " | " + costs[1] + " | Fictional request accounting only |\n"
        "| " + s["missing"] + " | not measured | not measured | Unknown, not zero or a null result |\n"
        "| Evidence budget | " + s["budget"] + " | " + s["budget"] + " | Fixed within this comparison |\n\n"
        "Table 2 notes. A missing condition prevents a cost contrast. Reported charges exclude unspecified staffing and maintenance, "
        "and do not represent a live vendor price. Retain the caption, units and notes with each row.\n\n")
    return table1, table2


def _case(s: dict) -> str:
    return ("Consider the authored case " + s["case_code"] + " in " + s["dataset"] + ". A question refers to a specific " + s["unit"] +
        " whose version-specific exception note narrows a familiar label. Another record shares that label but belongs to a neighboring condition. "
        "The baseline can retrieve the neighboring record because its surface wording is more common. The intervention changes selection using " + s["safeguard"] +
        ", yet a correctly identified source can still lose the condition during answer assembly. The annotation ledger therefore stores the requested object, "
        "the governing condition, the version and the rejected alternative separately. This example illustrates " + s["failure"] +
        "; it is not an extra measured query, success count, or frequency estimate. A plausible illustration cannot replace Table 1. "
        "An answer about a historical version must retain the historical exception even if a newer record is easier to retrieve. "
        "The example makes no claim about an actual organization, patient, legal entitlement, investment, device or physical procedure. "
        "Its role is to expose the exact applicability distinction that a compressed answer could accidentally erase.")


def _sharing(s: dict) -> str:
    if s["shared_data"]:
        return ("Data dependence declaration. This is a distinct study, but it shares the underlying authored case panel " + s["study_group_id"] +
            " with study " + s["paired_study_id"] + ". The two studies change method, language configuration or endpoint while reusing the panel's underlying cases. "
            "Translated surface forms and a different score do not turn that panel into independent evidence. This paper uses release " + s["release"] +
            ". Keep both study records, but group the shared panel before counting independent data groups or pooling sample sizes.")
    return ("Data dependence declaration. The authored case panel for this study is " + s["study_group_id"] + "; no other manuscript in this fixture reuses that panel. "
        "This local declaration describes the supplied synthetic inventory, not statistical independence of all possible mechanisms or a real population. "
        "This paper uses release " + s["release"] + ". A reviewer should distinguish study identifiers, document versions and underlying case panels.")


def protocol_note(s: dict, index: int) -> str:
    # Bounded substantive method notes; no additional measured endpoints.
    focuses = ("source identity", "condition matching", "version selection", "citation boundary", "subgroup membership", "abstention record",
               "question wording", "annotation disagreement", "evidence-budget equality", "update provenance", "rare-case applicability", "resource boundary")
    focus = focuses[(index + s["domain_index"] + s["family"]) % len(focuses)]
    return ("Protocol clarification " + str(index + 1) + " for " + s["case_code"] + " concerns " + focus + ". "
        "The audit trail links each question to the selected " + s["unit"] + ", its release marker, and the exception note retained in the answer. "
        "A reviewer may inspect that link without treating a valid identifier as automatic scientific support. The same passage can be relevant to one condition "
        "and irrelevant to another; the declared " + s["language"] + " workload and " + s["update"] + " remain applicability conditions. "
        "These records document the specified comparison rather than adding another favorable result. They neither fill the missing measurement of " + s["missing"] +
        " nor show that the persistent failure has disappeared. If a later evaluation changes this rule, it must name its new source release and report its own contrast.")


def render_paper(s: dict, *, extra_notes: int = 0) -> str:
    values = derived(s)
    blocks = ["# SYNTHETIC " + s["id"] + ": " + s["title"] + "\n\n",
        "SYNTHETIC BENCHMARK MANUSCRIPT. Entirely fictional research; all datasets, scores, intervals, costs, examples and outcomes are invented. "
        "No real authors, publication date, DOI, external publication claim or practical recommendation is supplied. "
        "The ten page markers are page-equivalent Markdown sections, not typeset PDF pages.\n\n"]
    t1, t2 = _tables(s)
    for page, (heading, paragraphs) in enumerate(__STATIC_PAGES__, 1):
        blocks.append("## Page %02d of 10 — %s\n\n" % (page, heading))
        for paragraph in paragraphs:
            blocks.append(paragraph.format_map(values) + "\n\n")
        if page == 2:
            blocks.extend([_case(s) + "\n\n", _sharing(s) + "\n\n"])
        if page == 6:
            blocks.append(t1)
        if page == 8:
            blocks.append(t2)
        if extra_notes > 0:
            for note in range(page - 1, extra_notes, 10):
                blocks.append(protocol_note(s, note) + "\n\n")
        if page == 10 and s["late_failure"]:
            blocks.append("Late source inspection. " + s["late_failure"] +
                ". This failure persisted despite the safeguard described above. It was found in the final inspection, "
                "not resolved by the favorable subset of traces, and has no separately measured failure frequency. "
                "Retain it as a qualitative limitation alongside the numeric primary and subgroup results; do not convert it into a new effect size.\n\n")
    return "".join(blocks)


def load_counter(path: Path) -> tuple[Callable[[str], int], dict]:
    """Read a local tokenizer only; no download, model weights or remote code."""
    from tokenizers import Tokenizer
    tokenizer = Tokenizer.from_file(str(path))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return lambda text: len(tokenizer.encode(text, add_special_tokens=False).ids), {
        "model": "Qwen/Qwen3.8-27B", "tokenizer_sha256": sha256(path.read_bytes()).hexdigest(),
        "method": "raw full Markdown text; add_special_tokens=False; no truncation or padding; not wire usage"}


def make_paper(s: dict, counter: Callable[[str], int] | None = None,
               min_tokens: int = 6500, max_tokens: int = 9000) -> tuple[str, int | None]:
    notes = 0
    text = render_paper(s)
    if counter is None:
        # Word length is explicitly unmeasured as Qwen tokens.
        while len(text.split()) < 5350:
            notes += 1
            text = render_paper(s, extra_notes=notes)
        return text, None
    count = counter(text)
    target = max(min_tokens, min(max_tokens - 100, 7100 + (s["seed"] % 701)))
    while count < target:
        notes += 1
        text = render_paper(s, extra_notes=notes)
        count = counter(text)
        if notes > 40:
            raise ValueError("Local tokenizer requires too many protocol notes")
    if not min_tokens <= count <= max_tokens:
        raise ValueError("Paper %s raw token length %d is outside [%d,%d]; source is not truncated" % (s["id"], count, min_tokens, max_tokens))
    return text, count


def generate_dataset(out: Path, *, seed: int = DEFAULT_SEED, counter: Callable[[str], int] | None = None,
                     tokenizer_identity: dict | None = None, min_tokens: int = 6500, max_tokens: int = 9000) -> dict:
    """Prepare all content before creating a new output directory; never overwrite."""
    out = Path(out).resolve()
    if out.exists():
        raise FileExistsError("Refusing to overwrite existing fixture directory: " + str(out))
    if not 1 <= min_tokens <= max_tokens:
        raise ValueError("Invalid token bounds")
    studies = build_studies(seed)
    prepared = [(s, *make_paper(s, counter, min_tokens, max_tokens)) for s in studies]
    out.mkdir(parents=True, exist_ok=False)
    papers = out / "papers"
    papers.mkdir()
    manifest, rows, gold = [], [], []
    for s, text, tokens in prepared:
        filename = s["id"].lower() + ".md"
        data = text.encode("utf-8")
        (papers / filename).write_bytes(data)
        digest = sha256(data).hexdigest()
        manifest.append({"path": filename, "paper_id": s["paper_id"], "metadata": {
            "title": "SYNTHETIC " + s["id"] + ": " + s["title"], "synthetic": True,
            "study_group_id": s["study_group_id"]}})
        rows.append({"paper_id": s["paper_id"], "path": "papers/" + filename,
                     "sha256": digest, "utf8_bytes": len(data), "words": len(text.split()),
                     "raw_qwen_tokens": tokens, "page_markers": 10})
        gold.append(dict(s, source_path="papers/" + filename, source_sha256=digest))
    spec = {"mode": "review", "questions": [
        {"question_id": "effects", "text": "What effects, uncertainty and counterevidence do these supplied studies report for retrieval and RAG interventions under their native metrics and designs?", "terms": ["primary", "subgroup", "interval", "intervention", "failure"]},
        {"question_id": "conditions", "text": "How do language overlap, update conditions, resource measurements and validity threats constrain interpretation and cross-study comparisons?", "terms": ["language", "update", "cost", "not measured", "validity"]},
        {"question_id": "dependence", "text": "Which studies share underlying case panels, and how should that affect counts of independent evidence?", "terms": ["shared", "panel", "independent", "release"]}],
        "comparison_dimensions": ["method_design_and_applicability", "outcomes_counterevidence_and_resources", "shared_data_and_comparability"]}
    counts = [row["raw_qwen_tokens"] for row in rows if row["raw_qwen_tokens"] is not None]
    summary = {"generator_version": GENERATOR_VERSION, "seed": seed, "papers": 100, "logical_papers": 100,
        "underlying_data_groups": len({s["study_group_id"] for s in studies}), "page_equivalents_per_paper": 10,
        "tokenizer": tokenizer_identity, "token_lengths_measured": counter is not None,
        "raw_token_bounds": {"requested_min": min_tokens, "requested_max": max_tokens,
                             "observed_min": min(counts) if counts else None, "observed_max": max(counts) if counts else None,
                             "total": sum(counts) if counts else None},
        "limitations": ["Template-based authored engineering fixture, not real literature or an academic quality benchmark.",
                        "Research conditions and quantitative values vary; common prose remains deliberately shared.",
                        "Page markers are not rendered physical pages; raw text token counts exclude chat framing.",
                        "Gold labels are host-only and must not be supplied to readers, writers or verifiers.",
                        "The manuscripts are English descriptions of evaluated language configurations, not 100 multilingual manuscripts."],
        "documents": rows}
    host_gold = {"host_only": True, "do_not_send_to_models": True, "generator_version": GENERATOR_VERSION,
        "seed": seed, "studies": gold, "expected_data_group_count": 80,
        "universal_controls": {"all_papers_are_synthetic": True, "no_studies_share_a_language": False,
                               "all_primary_intervals_establish_benefit": False, "all_subgroups_benefit": False,
                               "all_monetary_costs_are_zero": False, "all_100_studies_use_independent_data": False},
        "outcome_counts": dict(Counter(s["primary"]["interpretation"] for s in studies))}
    for filename, value in (("corpus-manifest.json", {"documents": manifest}), ("spec.json", spec),
                            ("manifest-summary.json", summary), ("gold.json", host_gold)):
        (out / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--tokenizer-json", type=Path)
    parser.add_argument("--min-tokens", type=int, default=6500)
    parser.add_argument("--max-tokens", type=int, default=9000)
    args = parser.parse_args(argv)
    counter, identity = load_counter(args.tokenizer_json) if args.tokenizer_json else (None, None)
    summary = generate_dataset(args.out, seed=args.seed, counter=counter, tokenizer_identity=identity,
                               min_tokens=args.min_tokens, max_tokens=args.max_tokens)
    print(json.dumps({key: value for key, value in summary.items() if key != "documents"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
