#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("usage: mortality_validation.R patient_level.csv share_output_dir")
input <- args[[1]]
outdir <- args[[2]]
dir.create(outdir, recursive = TRUE, showWarnings = FALSE)
.libPaths(c(normalizePath(".r-lib", mustWork = FALSE), .libPaths()))

required <- c("ggplot2", "pROC", "survival", "prodlim", "cmprsk")
missing <- required[!vapply(required, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) stop("missing required R packages: ", paste(missing, collapse = ", "))

suppressPackageStartupMessages({
  library(ggplot2)
  library(pROC)
  library(cmprsk)
  library(survival)
})

d <- read.csv(input, stringsAsFactors = FALSE, na.strings = c("", "NA", "None", "null"))
suppress_small <- function(x) ifelse(!is.na(x) & x < 5, "<5", as.character(x))
as_bool <- function(x) {
  value <- tolower(as.character(x)) == "true"
  value[is.na(value)] <- FALSE
  value
}
is_false <- function(x) !is.na(x) & tolower(as.character(x)) == "false"
boolean_columns <- grep(
  "^(complete_[0-9]+d|death_|transplant_|same_day_|landmark_eligible$|incident_aclf_90d$|incident_complete_|incident_death_|incident_transplant_)",
  names(d), value = TRUE
)
for (nm in boolean_columns) {
  d[[nm]] <- as_bool(d[[nm]])
}
score_cols <- c("clif_c_aclf_score", "clif_c_ad_score", "meld_score", "meld_na_score", "child_pugh_score")
incident_score_cols <- c("incident_clif_c_aclf_score", "incident_meld_score", "incident_meld_na_score", "incident_child_pugh_score")
for (nm in c(score_cols, incident_score_cols)) if (nm %in% names(d)) d[[nm]] <- as.numeric(d[[nm]])

score_labels <- c(
  clif_c_aclf_score = "CLIF-C ACLF",
  clif_c_ad_score = "CLIF-C AD",
  meld_score = "MELD",
  meld_na_score = "MELD-Na",
  child_pugh_score = "Child-Pugh"
)

roc_metrics <- list()
make_roc <- function(data, endpoint, scores, title, filename, analysis_set) {
  keep <- data[[paste0("complete_", endpoint, "d")]] &
    !data[[paste0("transplant_", endpoint, "d")]] &
    !data$same_day_death_transplant & complete.cases(data[, scores, drop = FALSE])
  x <- data[keep, , drop = FALSE]
  outcome <- x[[paste0("death_", endpoint, "d")]]
  n_event <- sum(outcome)
  n_nonevent <- sum(!outcome)
  powered <- n_event >= 10 && n_nonevent >= 10
  if (!powered) {
    p <- ggplot() + theme_void() +
      annotate("text", x = 0, y = 0, label = sprintf("Descriptive only: %d deaths, %d non-deaths", n_event, n_nonevent), size = 5) +
      labs(title = title, subtitle = paste(analysis_set, "did not meet the prespecified 10/10 event gate"))
    ggsave(filename, p, width = 7.5, height = 6, dpi = 300)
    ggsave(sub("\\.png$", ".pdf", filename), p, width = 7.5, height = 6)
    return(invisible(NULL))
  }
  rocs <- lapply(scores, function(score) roc(outcome, x[[score]], quiet = TRUE, direction = "<"))
  names(rocs) <- unname(score_labels[scores])
  for (score in scores) {
    rr <- rocs[[unname(score_labels[[score]])]]
    ci <- ci.auc(rr, method = "delong")
    roc_metrics[[length(roc_metrics) + 1]] <<- data.frame(
      figure = title, analysis_set = analysis_set, endpoint_days = endpoint,
      score = score_labels[[score]], n = nrow(x), deaths = n_event,
      auroc = as.numeric(auc(rr)), ci_low = as.numeric(ci[1]), ci_high = as.numeric(ci[3])
    )
  }
  subtitle <- sprintf("%s; paired complete cases n=%d, deaths=%d; transplant before horizon excluded", analysis_set, nrow(x), n_event)
  p <- ggroc(rocs, legacy.axes = TRUE, size = 1.1) +
    geom_abline(intercept = 0, slope = 1, linetype = 2, colour = "grey55") +
    coord_equal() + theme_minimal(base_size = 12) +
    labs(title = title, subtitle = subtitle, x = "1 - Specificity", y = "Sensitivity", colour = NULL)
  ggsave(filename, p, width = 7.5, height = 6, dpi = 300)
  ggsave(sub("\\.png$", ".pdf", filename), p, width = 7.5, height = 6)
}

fig5_scores <- c("clif_c_ad_score", "meld_score", "meld_na_score", "child_pugh_score")
fig6_scores <- c("clif_c_aclf_score", "meld_score", "meld_na_score", "child_pugh_score")

fig5_test <- d$analysis_split == "test" & is_false(d$baseline_aclf_present)
fig6_test <- d$analysis_split == "test" & as_bool(d$baseline_aclf_present) & d$baseline_group %in% c("ACLF-1", "ACLF-2", "ACLF-3")
fig5_full <- is_false(d$baseline_aclf_present)
fig6_full <- as_bool(d$baseline_aclf_present) & d$baseline_group %in% c("ACLF-1", "ACLF-2", "ACLF-3")

make_roc(d[fig5_test, ], 90, fig5_scores, "Figure 5 analogue: admission scores and 90-day mortality", file.path(outdir, "figure5_roc_locked_test.png"), "Locked 30% test set")
make_roc(d[fig5_full, ], 90, fig5_scores, "Figure 5 analogue: admission scores and 90-day mortality", file.path(outdir, "figure5_roc_full_exploratory.png"), "Full cohort exploratory")
make_roc(d[fig6_test, ], 28, fig6_scores, "Figure 6 analogue: ACLF diagnosis scores and 28-day mortality", file.path(outdir, "figure6_roc_locked_test.png"), "Locked 30% test set")
make_roc(d[fig6_full, ], 28, fig6_scores, "Figure 6 analogue: ACLF diagnosis scores and 28-day mortality", file.path(outdir, "figure6_roc_full_exploratory.png"), "Full cohort exploratory")

# Secondary analysis: first ACLF diagnosis during the 90 days after a non-ACLF index admission.
incident <- d[d$incident_aclf_90d & d$incident_complete_28d, , drop = FALSE]
if (nrow(incident)) {
  names(incident)[match(c("incident_complete_28d", "incident_death_28d", "incident_transplant_28d"), names(incident))] <-
    c("complete_28d", "death_28d", "transplant_28d")
  incident_scores <- c("incident_clif_c_aclf_score", "incident_meld_score", "incident_meld_na_score", "incident_child_pugh_score")
  score_labels[incident_scores] <- c("CLIF-C ACLF", "MELD", "MELD-Na", "Child-Pugh")
  make_roc(incident, 28, incident_scores,
    "Secondary analysis: first incident ACLF and 28-day mortality",
    file.path(outdir, "figure6_incident_aclf_roc_exploratory.png"), "Full cohort exploratory")
}

if (length(roc_metrics)) write.csv(do.call(rbind, roc_metrics), file.path(outdir, "roc_metrics.csv"), row.names = FALSE)

risk_rows <- list()
ad <- d[fig5_full & d$complete_90d & !d$transplant_90d & !is.na(d$clif_c_ad_score), ]
ad$risk_group <- cut(ad$clif_c_ad_score, breaks = c(-Inf, 45, 59, Inf), labels = c("<=45", "46-59", ">=60"))
for (grp in levels(ad$risk_group)) {
  z <- ad[ad$risk_group == grp, ]
  if (!nrow(z)) next
  bt <- binom.test(sum(z$death_90d), nrow(z))
  risk_rows[[length(risk_rows) + 1]] <- data.frame(
    clif_c_ad_group = grp, n = nrow(z), deaths_90d = sum(z$death_90d),
    observed_mortality = mean(z$death_90d), ci_low = bt$conf.int[1], ci_high = bt$conf.int[2]
  )
}
if (length(risk_rows)) {
  risk_table <- do.call(rbind, risk_rows)
  small <- risk_table$n < 5 | risk_table$deaths_90d < 5
  risk_table$observed_mortality[small] <- NA
  risk_table$ci_low[small] <- NA
  risk_table$ci_high[small] <- NA
  risk_table$n <- suppress_small(risk_table$n)
  risk_table$deaths_90d <- suppress_small(risk_table$deaths_90d)
  write.csv(risk_table, file.path(outdir, "clif_c_ad_risk_groups.csv"), row.names = FALSE)
}

cif_frame <- function(data, time_col, status_col, group_col, horizon, panel) {
  x <- data[!is.na(data[[time_col]]) & !is.na(data[[status_col]]) & !is.na(data[[group_col]]), ]
  x <- x[x[[time_col]] <= horizon, ]
  if (!nrow(x)) return(list(curves = data.frame(), tests = data.frame()))
  fit <- cuminc(x[[time_col]], x[[status_col]], factor(x[[group_col]]), cencode = 0)
  components <- names(fit)[grepl(" 1$", names(fit))]
  pieces <- lapply(components, function(nm) {
    obj <- fit[[nm]]
    data.frame(
      time = obj$time,
      estimate = obj$est,
      lower = pmax(0, obj$est - 1.96 * sqrt(obj$var)),
      upper = pmin(1, obj$est + 1.96 * sqrt(obj$var)),
      group = sub(" 1$", "", nm), panel = panel
    )
  })
  tests <- data.frame()
  if (!is.null(fit$Tests) && nrow(fit$Tests)) {
    tests <- data.frame(
      panel = panel,
      event_code = rownames(fit$Tests),
      statistic = fit$Tests[, "stat"],
      df = fit$Tests[, "df"],
      p_value = fit$Tests[, "pv"],
      row.names = NULL
    )
  }
  list(curves = do.call(rbind, pieces), tests = tests)
}

six_levels <- c("SDC", "UDC", "pre-ACLF", "ACLF-1", "ACLF-2", "ACLF-3")
six <- d[d$six_group %in% six_levels & !d$death_before_index & !d$transplant_before_index & !d$same_day_death_transplant, ]
six$six_group <- factor(six$six_group, levels = six_levels)
c1 <- cif_frame(six, "followup_days", "event_status_360", "six_group", 360, "Admission to day 360 (retrospective six groups)")
lm <- d[d$landmark_eligible & d$six_group %in% c("SDC", "UDC", "pre-ACLF") & !d$same_day_death_transplant, ]
lm$six_group <- factor(lm$six_group, levels = c("SDC", "UDC", "pre-ACLF"))
c2 <- cif_frame(lm, "landmark_followup_days", "landmark_event_status", "six_group", 270, "Day-90 landmark to day 360")
cif <- rbind(c1$curves, c2$curves)
gray_tests <- rbind(c1$tests, c2$tests)
if (nrow(gray_tests)) write.csv(gray_tests, file.path(outdir, "gray_tests.csv"), row.names = FALSE)
if (nrow(cif)) {
  p <- ggplot(cif, aes(time, estimate, colour = group, fill = group)) +
    geom_step(linewidth = 0.9) +
    geom_ribbon(aes(ymin = lower, ymax = upper), alpha = 0.12, colour = NA) +
    facet_wrap(~panel, scales = "free_x") +
    scale_y_continuous(labels = function(x) paste0(round(100 * x), "%"), limits = c(0, 1)) +
    theme_minimal(base_size = 12) +
    labs(title = "Figure 1B analogue: cumulative incidence of EHR-recorded death", x = "Days", y = "Cumulative incidence", colour = NULL, fill = NULL)
  ggsave(file.path(outdir, "figure1b_cumulative_incidence.png"), p, width = 11, height = 5.8, dpi = 300)
  ggsave(file.path(outdir, "figure1b_cumulative_incidence.pdf"), p, width = 11, height = 5.8)
}

# Prespecified sensitivity: censor at transplant and estimate ordinary survival curves.
if (nrow(six)) {
  km <- survfit(Surv(followup_days, event_status_360 == 1) ~ six_group, data = six)
  km_frame <- data.frame(
    time = km$time,
    mortality = 1 - km$surv,
    lower = 1 - km$upper,
    upper = 1 - km$lower,
    group = sub("^six_group=", "", rep(names(km$strata), km$strata))
  )
  pk <- ggplot(km_frame, aes(time, mortality, colour = group)) +
    geom_step(linewidth = 0.9) +
    theme_minimal(base_size = 12) +
    scale_y_continuous(labels = function(x) paste0(round(100 * x), "%"), limits = c(0, 1)) +
    labs(title = "Sensitivity analysis: transplant-censored mortality", x = "Days from admission", y = "Estimated mortality", colour = NULL)
  ggsave(file.path(outdir, "figure1b_transplant_censored_sensitivity.png"), pk, width = 8, height = 6, dpi = 300)
  ggsave(file.path(outdir, "figure1b_transplant_censored_sensitivity.pdf"), pk, width = 8, height = 6)
}

# Harrell concordance with transplantation censored at its observed time.
concordance_rows <- list()
add_concordance <- function(data, horizon, scores, label) {
  x <- data[data[[paste0("complete_", horizon, "d")]] & !data$same_day_death_transplant, , drop = FALSE]
  for (score in scores) {
    z <- x[!is.na(x[[score]]), , drop = FALSE]
    if (!nrow(z)) next
    time <- pmin(z$followup_days, horizon)
    event <- z$event_status_360 == 1 & z$followup_days <= horizon
    fit <- survival::concordance(Surv(time, event) ~ z[[score]], reverse = TRUE)
    concordance_rows[[length(concordance_rows) + 1]] <<- data.frame(
      analysis = label, score = score_labels[[score]], n = nrow(z), deaths = sum(event),
      concordance = unname(fit$concordance), standard_error = sqrt(unname(fit$var))
    )
  }
}
add_concordance(d[fig5_full, ], 90, fig5_scores, "Figure 5 full cohort; transplant-censored")
add_concordance(d[fig6_full, ], 28, fig6_scores, "Figure 6 full cohort; transplant-censored")
if (length(concordance_rows)) {
  concordance_table <- do.call(rbind, concordance_rows)
  small <- concordance_table$n < 5 | concordance_table$deaths < 5
  concordance_table$concordance[small] <- NA
  concordance_table$standard_error[small] <- NA
  concordance_table$n <- suppress_small(concordance_table$n)
  concordance_table$deaths <- suppress_small(concordance_table$deaths)
  write.csv(concordance_table, file.path(outdir, "transplant_censored_concordance.csv"), row.names = FALSE)
}

if (nrow(six)) {
  group_summary <- aggregate(
    cbind(death_360d = as.integer(six$death_360d), transplant_360d = as.integer(six$transplant_360d)),
    list(group = six$six_group), sum, na.rm = TRUE
  )
  group_n <- aggregate(person_id ~ six_group, six, length)
  names(group_n) <- c("group", "n")
  group_summary <- merge(group_n, group_summary, by = "group", all = TRUE)
  group_summary$stability_warning <- group_summary$n < 10 | group_summary$death_360d < 3
  group_summary$n <- suppress_small(group_summary$n)
  group_summary$death_360d <- suppress_small(group_summary$death_360d)
  group_summary$transplant_360d <- suppress_small(group_summary$transplant_360d)
  write.csv(group_summary, file.path(outdir, "six_group_summary.csv"), row.names = FALSE)
}

flow_path <- file.path(dirname(input), "cohort_flow.csv")
if (file.exists(flow_path)) {
  flow <- read.csv(flow_path, stringsAsFactors = FALSE)
  flow$n <- suppress_small(flow$n)
  write.csv(flow, file.path(outdir, "cohort_flow.csv"), row.names = FALSE, quote = FALSE)
}
completeness_path <- file.path(dirname(input), "score_completeness.csv")
if (file.exists(completeness_path)) {
  completeness <- read.csv(completeness_path, stringsAsFactors = FALSE)
  for (nm in c("available", "missing", "eligible_total")) completeness[[nm]] <- suppress_small(completeness[[nm]])
  write.csv(completeness, file.path(outdir, "score_completeness.csv"), row.names = FALSE, quote = FALSE)
}

readme <- c(
  "# ACLF mortality validation",
  "",
  "This bundle reports an IU single-center, retrospective internal validation using EHR-recorded death.",
  "It is aligned to the time-zero and outcome definitions used by the EASL-CLIF studies, but it is not a direct replication of CANONIC or PREDICT.",
  "",
  "## What the figures show",
  "",
  "- Figure 1B analogue: mortality cumulative incidence across the six clinical trajectories, with liver transplantation treated as a competing event. Gray's tests are reported separately.",
  "- Figure 5 analogue: admission prognostic scores among acute decompensation without ACLF and 90-day mortality.",
  "- Figure 6 analogue: prognostic scores at ACLF diagnosis and 28-day mortality.",
  "",
  "The locked 30% test-set ROC is the prespecified primary discrimination result. Full-cohort and incident-ACLF ROC plots are exploratory.",
  "The transplant-censored concordance and survival plot are sensitivity analyses; they do not replace the competing-risk cumulative-incidence analysis.",
  "ROC plots are descriptive when fewer than 10 deaths or 10 non-deaths are available.",
  "Cells smaller than five are suppressed in audience-facing tables.",
  "",
  "## Important limitation",
  "",
  "Death is derived from the OMOP status 'EHR record patient status Deceased'. Out-of-system deaths may be missed, so these results must not be described as complete vital-status ascertainment.",
  "No patient identifiers, prompts, retrieval traces, or model state are included in this bundle."
)
writeLines(readme, file.path(outdir, "README.md"))
