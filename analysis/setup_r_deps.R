#!/usr/bin/env Rscript

# Run once before submitting mortality_validation.sbatch. The analysis job itself
# never downloads packages.
lib <- normalizePath(".r-lib", mustWork = FALSE)
dir.create(lib, recursive = TRUE, showWarnings = FALSE)
.libPaths(c(lib, .libPaths()))
if (!requireNamespace("cmprsk", quietly = TRUE)) {
  install.packages("cmprsk", repos = "https://cloud.r-project.org", lib = lib)
}
stopifnot(requireNamespace("cmprsk", quietly = TRUE))

