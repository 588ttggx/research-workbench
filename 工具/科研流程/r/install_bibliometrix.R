args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("Provide library and package cache directories")
dir.create(args[1], recursive = TRUE, showWarnings = FALSE)
dir.create(args[2], recursive = TRUE, showWarnings = FALSE)
.libPaths(c(normalizePath(args[1], winslash = "/"), .libPaths()))
options(repos = c(CRAN = "https://cloud.r-project.org"), timeout = 300)
if (!requireNamespace("bibliometrix", quietly = TRUE)) install.packages("bibliometrix", lib = args[1], destdir = args[2],
                 dependencies = NA, type = "binary")
# Biblioshiny loads these explicitly beyond the core package's Imports. Use the
# installed vendor list so its application dependencies stay aligned with R.
vendor <- file.path(find.package("bibliometrix"), "biblioshiny", "libraries.R")
code <- readLines(vendor, warn = FALSE)
start <- grep('  pkgs <- c\\(', code, fixed = FALSE)[1]
end <- start + which(trimws(code[(start+1):length(code)]) == ")")[1]
packages <- sub('^[[:space:]]*"([^" ]+).*', '\\1', code[(start+1):(end-1)])
packages <- packages[grepl('^[A-Za-z][A-Za-z0-9.]+$', packages)]
missing <- packages[!vapply(packages, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) install.packages(missing, lib = args[1], destdir = args[2], dependencies = NA, type = "binary")
remaining <- packages[!vapply(packages, requireNamespace, logical(1), quietly = TRUE)]
if (length(remaining)) stop(paste("Biblioshiny dependencies missing:", paste(remaining, collapse = ", ")))
if (!requireNamespace("bibliometrix", quietly = TRUE)) stop("Bibliometrix is not available")
cat("BIBLIOMETRIX_VERSION=", as.character(packageVersion("bibliometrix")), "\n", sep = "")
