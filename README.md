# Experimental Data Package

**Manuscript title:**  
*Multi-Objective Multi-UAV IoT Data Collection under Age of Information and Grey Time Window Preferences*

This repository provides the experimental data associated with a manuscript currently under review.

To support peer review and editorial assessment, the repository includes the data underlying the reported computational results, including scenario instances, run-level result summaries, manuscript-ready tables, and figure-source CSV files. The source code of the optimization algorithms and the full experimental pipeline are not released at the review stage and will be made publicly available after paper acceptance.

The study investigates multi-UAV IoT data collection under two coupled requirements: information freshness and service-time preference. The reported experiments evaluate a joint age-of-information and grey-time-window optimization framework through main-comparison experiments, ablation experiments, sensitivity analysis, and model-variant analysis.

## Scope of the release

This release is intentionally lightweight. It is designed to expose the data required to inspect the reported results without distributing the full research codebase or several gigabytes of intermediate raw run files.

Included in the current release:

- `main_study/`
  Data for the main algorithm comparison and ablation experiments.
- `sensitivity/`
  Data for the key parameter sensitivity experiments.
- `model_variants/`
  Data for the structural model-variant experiments.

Not included in the current release:

- source code of the proposed optimization algorithms;
- the full experiment runner and plotting scripts;
- complete raw JSON outputs for all runs.

## Repository structure

```text
paper_data_under_review/
├── README.md
├── main_study/
│   ├── scenarios/
│   ├── runs/
│   ├── tables/
│   └── figure_source/
├── sensitivity/
│   ├── table_sensitivity_overall.csv
│   ├── omega_0.20/
│   ├── omega_0.30/
│   ├── omega_0.40/
│   ├── rmax_1/
│   ├── rmax_2/
│   ├── rmax_3/
│   └── uav_count/
└── model_variants/
    ├── table_model_variants_overall.csv
    ├── table_model_variants_by_group.csv
    ├── full_model/
    ├── multi_uav_one_sortie/
    ├── no_gtw/
    └── single_uav_reference/
```

## File conventions

- `*_runs.csv`
  Run-level outputs, where each row corresponds to one run on one scenario instance.
- `*_summary.csv`
  Aggregate summaries derived from run-level outputs.
- `*_scenario_summary.csv`
  Scenario-level aggregated results.
- `*_scenario_type_summary.csv`
  Aggregated results by scenario type.
- `*_group_summary.csv`
  Aggregated results by experiment group.
- `table_*.csv`
  Final tables used for manuscript reporting.

## Recommended entry points

- `main_study/scenarios/`
  Scenario-instance JSON files for the main study. These files describe the benchmark instances used in the manuscript, including the experiment group, scenario type, node coordinates, depot setting, key-node labels, and grey time window parameters.
- `main_study/runs/algorithm_quality_runs.csv`
  Main run-level data for the overall algorithm comparison.
- `main_study/tables/table_algorithm_overall.csv`
  Main manuscript table for the overall comparison.
- `main_study/runs/ablation_quality_runs.csv`
  Run-level data for the ablation study.
- `main_study/tables/table_ablation_overall.csv`
  Main manuscript table for the ablation study.
- `main_study/figure_source/`
  Source CSV files used to generate the representative Pareto, route, timeline, and convergence figures.
- `sensitivity/table_sensitivity_overall.csv`
  Overall summary of the sensitivity analysis.
- `model_variants/table_model_variants_overall.csv`
  Overall summary of the model-variant experiments.

## What is contained in `main_study/scenarios/`

The directory `main_study/scenarios/` contains the scenario instances used for the core experiments reported in the manuscript. These JSON files correspond to the main benchmark groups and mechanism-focused instances considered in the study:

- `main_30_3`
- `main_50_5`
- `main_80_7`
- `mechanism_50_4`

For each group, instances are provided for two scenario families:

- `multi_hotspot_boundary`
  Multi-cluster layouts with boundary/key-node pressure near cluster boundaries.
- `remote_hotspot`
  Layouts containing relatively remote hotspot structures that induce stronger sortie and timing coordination pressure.

Each scenario JSON file records the instance definition required to reproduce the reported data tables, including scenario metadata, node locations, node categories, and the grey-time-window parameters associated with service-time preference evaluation.

## Availability statement

The associated manuscript is under review. During the review stage, this repository is limited to the experimental data package only. The source code, full reproducibility scripts, and complete implementation details will be released after paper acceptance.
