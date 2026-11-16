args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 3) stop("Provide bibliography, output directory, and R library")
.libPaths(c(args[3], .libPaths()))
suppressPackageStartupMessages(library(bibliometrix))
suppressPackageStartupMessages(library(jsonlite))
dir.create(args[2], showWarnings = FALSE, recursive = TRUE)
source <- if (length(args) >= 4) args[4] else "zotero"
network_limit <- if (length(args) >= 5) as.integer(args[5]) else 300L
if (is.na(network_limit) || network_limit < 20L || network_limit > 1000L) stop("Invalid native network limit")
formats <- list(zotero=c("generic", "bibtex"), wos=c("wos", "plaintext"), scopus=c("scopus", "csv"), pubmed=c("pubmed", "pubmed"))
if (!source %in% names(formats)) stop("Unsupported bibliography format")
M <- convert2df(args[1], dbsource = formats[[source]][1], format = formats[[source]][2])
if (!is.data.frame(M) || !nrow(M)) stop("No bibliographic records were parsed")
for (field in names(M)) if (is.character(M[[field]])) {
  value <- trimws(M[[field]])
  M[[field]][is.na(value) | toupper(value) %in% c("", "NA", "NA NA", "NONE", "N/A")] <- NA_character_
}
# Zotero's BibTeX `keywords` are library tags, including operational tags and IDs.
# They must not masquerade as author keywords or Keywords Plus.
if (source == "zotero") { M$ID <- NA_character_; M$DE <- NA_character_ }
saveRDS(M, file.path(args[2], "corpus.rds"))
write.csv(M, file.path(args[2], "corpus.csv"), row.names = FALSE, fileEncoding = "UTF-8")
has <- function(field) field %in% names(M) && any(!is.na(M[[field]]) & nzchar(trimws(M[[field]])))
coverage <- setNames(lapply(c("AU", "PY", "SO", "DE", "ID", "CR", "C1", "AB"), function(f) {
  if (!f %in% names(M)) return(0L)
  sum(!is.na(M[[f]]) & nzchar(trimws(M[[f]])))
}), c("AU", "PY", "SO", "DE", "ID", "CR", "C1", "AB"))
result <- list(tool = "Bibliometrix", version = as.character(packageVersion("bibliometrix")),
               records = nrow(M), source = source, fields = coverage, networks = list(),network_limit=network_limit,
               notice = if (source == "zotero") "Selected Zotero corpus, not an exhaustive survey. Missing metadata is not inferred. Library tags are excluded from scientific keyword analysis; import a native bibliometric export for these analyses." else "Selected native bibliographic export, not an exhaustive survey. Missing metadata is not inferred. Bibliometrix's native n parameter is applied where supported; paper coupling can retain all documents. Actual network counts are reported and the complete input corpus is preserved.")
analysis <- tryCatch(biblioAnalysis(M, sep = ";"), error = function(e) NULL)
if (!is.null(analysis)) saveRDS(analysis, file.path(args[2], "bibliographic-analysis.rds"))
jobs <- list(
  list(id="author-collaboration", analysis="collaboration", network="authors", required="AU"),
  list(id="keyword-cooccurrence", analysis="co-occurrences", network="author_keywords", required="DE"),
  list(id="keywordplus-cooccurrence", analysis="co-occurrences", network="keywords", required="ID"),
  list(id="institution-collaboration", analysis="collaboration", network="universities", required="C1"),
  list(id="paper-coupling", analysis="coupling", network="references", required="CR"),
  list(id="reference-cocitation", analysis="co-citation", network="references", required="CR")
)
for (job in jobs) {
  if (!has(job$required)) {
    result$networks[[job$id]] <- list(status="missing_metadata", required=job$required)
    next
  }
  tryCatch({
    matrix <- biblioNetwork(M, analysis=job$analysis, network=job$network,n=network_limit, sep=";")
    saveRDS(matrix, file.path(args[2], paste0(job$id,".rds")))
    graph <- igraph::graph_from_adjacency_matrix(matrix, mode="undirected", weighted=TRUE, diag=FALSE)
    if (!igraph::vcount(graph)) stop("No usable nodes in this metadata field")
    graph <- igraph::set_vertex_attr(graph, "id", value=seq_len(igraph::vcount(graph))-1L)
    graph <- igraph::set_vertex_attr(graph, "label", value=igraph::vertex_attr(graph, "name"))
    igraph::write_graph(graph, file.path(args[2], paste0(job$id,".gml")), format="gml", id=seq_len(igraph::vcount(graph))-1L)
    # VOSviewer's tabular interchange retains names without GML dialect ambiguity.
    write.table(data.frame(id=seq_len(igraph::vcount(graph)), label=igraph::vertex_attr(graph,"name")),
                file.path(args[2],paste0(job$id,"-map.txt")), sep="\t", quote=FALSE, row.names=FALSE, fileEncoding="UTF-8")
    endpoints <- igraph::as_edgelist(graph, names=FALSE)
    write.table(cbind(endpoints, igraph::edge_attr(graph,"weight")),
                file.path(args[2],paste0(job$id,"-network.txt")), sep="\t", quote=FALSE,
                row.names=FALSE, col.names=FALSE, fileEncoding="UTF-8")
    n <- min(60L, nrow(matrix))
    if (n > 1 && igraph::ecount(graph) > 0) {
      svg(file.path(args[2], paste0(job$id,".svg")), width=12, height=8)
      tryCatch(networkPlot(matrix, n=n, type="fruchterman", Title=job$id,
                           size=5, labelsize=0.7, remove.isolates=TRUE, verbose=TRUE),
               finally=dev.off())
    }
    result$networks[[job$id]] <- list(status="exported", nodes=nrow(matrix), edges=igraph::ecount(graph),
                                      gml=paste0(job$id,".gml"))
  }, error=function(e) {
    result$networks[[job$id]] <<- list(status="unavailable", message=conditionMessage(e))
  })
}
if (has("CR") && has("PY")) {
  result$historiograph <- tryCatch({
    hist <- histNetwork(M, sep=";");saveRDS(hist,file.path(args[2],"historiograph.rds"))
    picture <- histPlot(hist,n=30,verbose=FALSE)
    if (!is.null(picture$g)) ggplot2::ggsave(file.path(args[2],"historiograph.svg"),picture$g,width=14,height=9,device=grDevices::svg)
    list(status="exported",figure=if(!is.null(picture$g)) "historiograph.svg" else NULL)
  },error=function(e) list(status="unavailable",message=conditionMessage(e)))
} else result$historiograph <- list(status="missing_metadata",required=c("CR","PY"))
if (has("DE")) {
  result$thematic_map <- tryCatch({
    theme <- thematicMap(M, field="DE", n=100, minfreq=2, stemming=FALSE)
    saveRDS(theme,file.path(args[2],"thematic-map.rds"))
    if (!is.null(theme$map)) ggplot2::ggsave(file.path(args[2],"thematic-map.svg"),theme$map,width=12,height=9,device=grDevices::svg)
    list(status="exported",figure=if(!is.null(theme$map)) "thematic-map.svg" else NULL)
  },error=function(e) list(status="unavailable",message=conditionMessage(e)))
  years <- sort(unique(na.omit(M$PY)))
  if (length(years) >= 3) {
    result$thematic_evolution <- tryCatch({
    evolution <- thematicEvolution(M, field="DE", years=years[ceiling(length(years)/2)], n=100, minFreq=2)
    saveRDS(evolution,file.path(args[2],"thematic-evolution.rds"))
    evolution_plot <- plotThematicEvolution(evolution$Nodes,evolution$Edges)
    writeLines(plotly::plotly_json(evolution_plot,jsonedit=FALSE,pretty=FALSE),file.path(args[2],"thematic-evolution.plotly.json"),useBytes=TRUE)
    list(status="exported",figure="thematic-evolution.plotly.json")
    },error=function(e) list(status="unavailable",message=conditionMessage(e)))
  } else result$thematic_evolution <- list(status="missing_metadata",required=c("PY", "years"))
} else {
  result$thematic_map <- list(status="missing_metadata",required="DE")
  result$thematic_evolution <- list(status="missing_metadata",required=c("DE","PY"))
}
if (has("DE") && has("PY")) {
 result$trends <- tryCatch({
  trend <- fieldByYear(M, field="DE", timespan=range(as.numeric(M$PY),na.rm=TRUE),
                       min.freq=2, n.items=5, dynamic.plot=FALSE, graph=FALSE)
  saveRDS(trend,file.path(args[2],"trend-topics.rds"))
  if (!is.null(trend$graph)) ggplot2::ggsave(file.path(args[2],"trend-topics.svg"),trend$graph,width=12,height=8,device=grDevices::svg)
  list(status="exported",figure=if(!is.null(trend$graph)) "trend-topics.svg" else NULL)
 },error=function(e) list(status="unavailable",message=conditionMessage(e)))
} else result$trends <- list(status="missing_metadata",required=c("DE","PY"))
writeLines(capture.output(print(citation("bibliometrix"))),file.path(args[2],"software-citation.txt"))
write_json(result, file.path(args[2],"analysis.json"), pretty=TRUE, auto_unbox=TRUE, null="null")
cat("BIBLIOMETRIC_RECORDS=",nrow(M),"\n",sep="")
