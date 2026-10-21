# Whole-unit selector cold2：獨立 source→card 審查（先於 reviewer 結論）

只讀本次原始兩篇Markdown、本次新cards及其assigned reader findings／named dispositions。未讀歷史host audit或gold；未讀本次reviewer結論；沒有API、tokenizer、tests或live資料修改。

|Paper|Claims|字數|Retention|
|---|---:|---:|---|
|s01|9|1239|{'included': 60}|
|s08|12|1184|{'included': 106}|

核心數值、CI、主要子群反證、持續失敗與未測量結果大致保留；以下區分可直接核對的citation/named-binding缺口與需科學判斷的語氣精度。這不是完整品質通過。

## I01 s08: local_citation_gap

分類：confirmed；named claims=['c7']。

c7 specifies a monthly update schedule, but its only declared part p0053 says update schedule without a monthly cadence. The fact is available elsewhere in the same paper (p0009/p0004), not in this claim own citation. This is local citation closure, not an invented corpus fact.

## I02 s08: named_retention_mismatch

分類：confirmed；named claims=['c4']。

The assigned finding covers annotation-quality review and clinical utility remaining unmeasured after that exercise. Its dispositions name c4 and say these facts are retained there. c4 only describes persistent wrong-concept mapping and loss of qualifications. It does not state annotation-quality review or missing clinical utility. c6 contains missing utility elsewhere, which does not establish named c4 retention.

## I03 s08: named_retention_mismatch

分類：confirmed；named claims=['c6']。

The disposition expressly says workload 1880 questions against 14200 records is retained in c6. c6 includes costs, missing utility and five-abstract budget, but neither workload count. c1 includes the counts; it is not named by this disposition.

## I04 s08: named_retention_mismatch

分類：confirmed；named claims=['c11']。

The disposition claims that unmeasured downstream clinical utility and the Recall@5 operational boundary are retained in c11. c11 is about annotators, conflicts and consensus-label timing; it does not state the missing clinical-utility result or name Recall@5. Missing utility appears in c6, not the named claim.

## I05 s08: named_retention_mismatch

分類：confirmed；named claims=['c5']。

The finding concerns equal output policies/supported-answer definitions and source authority when an answer contradicts a source. The disposition says these policies are retained in c5, but c5 states the randomized experiment and narrow causal scope, with no equal-output-policy or source-authority statement. Shared methodological topic is not preservation.

## I06 s08: named_retention_mismatch

分類：confirmed；named claims=['c4']。

The finding states a minimum-complete-context assembly rule, value/unit/population binding and table caption/notes retention. The disposition names c4 and claims this rule is retained. c4 describes evidence losing a qualification in error traces, not the assembly protocol or table/context requirements.

## I07 s01: evidentiary_strength_precision

分類：requires_scientific_judgment；named claims=['c5']。

The original says qualitative traces suggest the mechanism changes evidence selection. c5 says traces show (顯示) it changed (改變了), while retaining bounded-design caveats. This may strengthen the evidentiary verb; it should be distinguished from an unequivocal factual contradiction.

## I08 s08: resource_boundary_precision

分類：requires_scientific_judgment；named claims=['c6']。

The original cost paragraph excludes unlogged maintenance work; c6 says maintenance costs are excluded without the unlogged qualification. The broad accounting caution is retained, but the exclusion boundary is less precise.

## I09 s01: population_label_precision

分類：requires_scientific_judgment；named claims=['c3']。

The cited subgroup is noisy curator-name queries; c3 calls it noisy curator-surname queries. Surname ambiguity motivates another part of the paper, but the subgroup citation does not explicitly restrict all names to surnames. This is a translation/scope precision concern, not a numeric discrepancy.

## 逐claim核心對照

|Paper/claim|Host note|
|---|---|
|s01/c1|Design, English museum corpus, 1840/12600, ten-record budget and narrow causal scope match own sources.|
|s01/c2|Recall@10 0.684→0.752, +0.068, CI [+0.041,+0.095], native-scale and aggregate-only bounds retained.|
|s01/c3|0.610→0.600, -0.010, CI [-0.040,+0.020], no clear subgroup benefit and required counterevidence retained; subgroup wording precision is I09.|
|s01/c4|Persistent failure after lexicon intervention and qualification loss match p0039.|
|s01/c5|Mechanism caveats and no universal inferiority retained; evidentiary verb strength is I07.|
|s01/c6|Monetary cost and faithfulness remain unmeasured/unknown, not zero; ten-record budget and cost-effectiveness gap retained.|
|s01/c7|Collection-age, authored collection, untested language and minority-use-case limitations match p0052/p0053.|
|s01/c8|Metric/population non-comparability and Recall@10 direction retained.|
|s01/c9|Synthetic/non-publication scope matches p0002/p0060.|
|s08/c1|BioGloss-Sim, Portuguese, 1880/14200, five-abstract budget and reference pipeline match sources.|
|s08/c2|Recall@5 0.612→0.659, +0.047, CI [+0.018,+0.076], aggregate-only scope retained.|
|s08/c3|0.583→0.544, -0.039, CI [-0.074,-0.004], adverse exclusion of zero and counterevidence retained.|
|s08/c4|Persistent near-synonym/wrong-concept failure and lost qualifications match p0039; the unrelated named dispositions remain I02/I06.|
|s08/c5|Randomization, two pipelines, frozen source/questions and narrow causal scope retained; query-pair pairing is not explicit in Chinese, a precision limitation.|
|s08/c6|USD0.021/0.031 and unmeasured clinical utility retained; maintenance-boundary precision is I08.|
|s08/c7|Authored corpus and untested-language/minority-case limits match p0053; monthly specificity lacks own locator (I01).|
|s08/c8|Terminology ambiguity, restricted causal inference and non-comparable metrics match own sources.|
|s08/c9|Seed1808, stable IDs, frozen digests, synthetic/non-publication and replication conditions retained.|
|s08/c10|p0058 supports unresolved wrong-concept challenge and separate future evaluation, not a success claim.|
|s08/c11|Annotator/local-context procedure, conflicts and consensus-label timing match p0026.|
|s08/c12|Synthetic/non-publication status matches p0002/p0060.|

本檔封存後才另讀reviewer。是否false-pass只按它對相同target/version的實際判定比較，不從TaskStore accepted狀態推論語義通過。
