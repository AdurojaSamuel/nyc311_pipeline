#!/usr/bin/env Rscript

#!/usr/bin/env Rscript

library(shiny)
library(plotly)
library(reticulate)

options(shiny.port = as.integer(Sys.getenv("SHINY_PORT", unset = "3838")))
options(shiny.host = Sys.getenv("SHINY_HOST", unset = "0.0.0.0"))

`%||%` <- function(x, y) if (is.null(x) || length(x) == 0) y else x

format_number <- function(value, digits = 0) {
  formatC(as.numeric(value), format = "f", digits = digits, big.mark = ",")
}

app_argument <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
script_path <- if (length(app_argument)) sub("^--file=", "", app_argument[[1]]) else ""
app_dir <- if (nzchar(script_path) && file.exists(script_path)) {
  dirname(normalizePath(script_path))
} else if (file.exists(file.path(getwd(), "app.R"))) {
  getwd()
} else {
  normalizePath("src")
}

data_root <- Sys.getenv(
  "NYC311_DATA_ROOT",
  unset = if (file.exists(file.path(app_dir, "dashboard_data.parquet"))) app_dir else file.path(app_dir, "..", "data")
)

dashboard_file <- file.path(
  data_root,
  "dashboard_data.parquet"
)

python_executable <- Sys.getenv(
  "NYC311_PYTHON",
  unset = Sys.getenv(
    "RETICULATE_PYTHON",
    unset = file.path(dirname(app_dir), ".venv", "bin", "python")
  )
)
if (!file.exists(python_executable)) {
  python_executable <- Sys.which("python3")
}
if (!nzchar(python_executable)) {
  stop("Python 3 is required for forecasting and MLflow tracking.")
}
reticulate::use_python(python_executable, required = TRUE)
reticulate::source_python(file.path(app_dir, "forecasting.py"))
reticulate::source_python(file.path(app_dir, "workforce.py"))

if (!file.exists(dashboard_file)) {
  stop(
    "Dashboard data not found at: ",
    dashboard_file
  )
}

data <- reticulate::import("pandas")$read_parquet(dashboard_file)
data$date <- as.Date(data$date)
data$borough <- toupper(trimws(data$borough))

boroughs <- c(
  "ALL",
  "BRONX",
  "BROOKLYN",
  "MANHATTAN",
  "QUEENS",
  "STATEN ISLAND",
  "UNKNOWN",
  "UNSPECIFIED"
)
series_for <- function(data_type, borough) {
  result <- data[data$date >= min(data$date) & data$date <= max(data$date), ]
  if (borough != "ALL") result <- result[result$borough == borough, ]
  column <- if (data_type == "OpenedSR") "opened" else "closed"
  if (!nrow(result)) return(data.frame(date = as.Date(character()), value = numeric()))
  result$value <- result[[column]]
  result[, c("date", "value")]
}
monthly_series <- function(data_type, borough) {
  values <- series_for(data_type, borough)
  if (!nrow(values)) return(ts(numeric(), frequency = 12))
  values$month <- as.Date(format(values$date, "%Y-%m-01"))
  monthly <- aggregate(value ~ month, values, sum)
  all_months <- seq(min(monthly$month), max(monthly$month), by = "month")
  monthly <- merge(data.frame(month = all_months), monthly, by = "month", all.x = TRUE)
  monthly$value[is.na(monthly$value)] <- 0
  start <- c(as.integer(format(min(monthly$month), "%Y")), as.integer(format(min(monthly$month), "%m")))
  ts(monthly$value, start = start, frequency = 12)
}

ui <- fluidPage(
  title = "Opened and Closed Service Requests",
  tags$head(tags$style(HTML("html, body { min-height: 100%; } body { overflow-y: auto; font-family: Arial, sans-serif; color: #333; } .title-panel { margin: 6px 1.5% 8px; } .control-panel { background: #f5f5f5; border: 1px solid #ddd; border-radius: 4px; padding: 16px; min-height: 214px; } .chart-panel { height: 38vh; } .forecast-panel { height: 48vh; } .orange-rule { border-top: 1px solid orange; margin: 18px 1.5% 14px; } .footnote { height: 5vh; line-height: 5vh; text-align: left; margin: 0; padding: 0 1.5%; position: relative; color: #666; font-size: 12px; } .copyright { position: absolute; left: 50%; transform: translateX(-50%); font-weight: 700; color: #1f3a5f; }"))),
  h4("Opened and Closed Service Requests", class = "title-panel"),
  fluidRow(
    column(4, div(class = "control-panel",
      radioButtons("data2view", "Data type", c("OpenedSR", "ClosedSR"), inline = TRUE), hr(),
      selectInput("borough", "Select Borough", choices = boroughs, selected = "ALL"), hr(),
      actionButton("view1", "view", class = "btn-primary")
    )),
    column(8, plotlyOutput("Plot", height = "38vh"))
  ),
  tags$hr(class = "orange-rule"),
  h4("Projecting Future Requests: Opened and Closed", style = "margin: 0 1.5% 8px; font-weight: 400;"),
  fluidRow(
    column(4, div(class = "control-panel",
      radioButtons("data2view1", "Data type", c("OpenedSR", "ClosedSR"), inline = TRUE), hr(),
      selectInput("borough1", "Select Borough", choices = boroughs, selected = "ALL"), hr(),
      numericInput("h", "Months to predict", value = 12, min = 1, max = 60),
      radioButtons("Model", "Model type", c("Best", "Holt-Winters", "AutoARIMA", "LSTM"), inline = TRUE, selected = "Best"),
      actionButton("view2", "view", class = "btn-primary")
    )),
    column(8, plotlyOutput("Plot2", height = "43vh"), textOutput("forecast_status"))
  ),
  tags$hr(class = "orange-rule"),
  h4("Call-Taker Staffing and Labor-Cost Optimization", style = "margin: 0 1.5% 8px; font-weight: 400;"),
  p(
    "Planning estimate: forecasts are treated as calls. Erlang-C staffing targets the selected service level, ",
    "with occupancy capped at the selected limit. Update assumptions before using the estimate operationally.",
    style = "margin: 0 1.5% 12px; color: #555;"
  ),
  fluidRow(
    column(4, div(class = "control-panel",
      selectInput("staffing_borough", "Select Borough", choices = boroughs, selected = "ALL"),
      selectInput("staffing_model", "Forecast model", choices = c("Best", "Holt-Winters", "AutoARIMA", "LSTM"), selected = "Best"),
      numericInput("calls_per_request", "Calls per service request", value = 1, min = 0, step = 0.1),
      numericInput("handle_time", "Average handle time (minutes)", value = 8, min = 1),
      numericInput("staffing_horizon", "Months to plan", value = 12, min = 1, max = 60),
      numericInput("hourly_wage", "Hourly wage ($)", value = 25, min = 0),
      numericInput("shrinkage", "Paid shrinkage (%)", value = 30, min = 0, max = 99),
      numericInput("operating_hours", "Operating hours per day", value = 8, min = 1, max = 24),
      numericInput("business_days", "Business days per month", value = 22, min = 1, max = 31),
      numericInput("service_target", "Service level target (%)", value = 80, min = 1, max = 99),
      numericInput("answer_seconds", "Answer target (seconds)", value = 20, min = 0),
      numericInput("occupancy_limit", "Occupancy limit (%)", value = 85, min = 1, max = 100),
      actionButton("optimize_staffing", "Optimize staffing", class = "btn-primary")
    )),
    column(8, plotlyOutput("staffing_plot", height = "48vh"), textOutput("staffing_summary"))
  ),
  tags$footer(class = "footnote",
    span("Data Source: NYC Open Data 311 Service Requests "),
    span(class = "copyright", "(c) Samuel Aduroja")
  )
)

server <- function(input, output, session) {
  history_data <- eventReactive(input$view1, series_for(input$data2view, input$borough), ignoreNULL = FALSE)
  forecast_data <- eventReactive(input$view2, monthly_series(input$data2view1, input$borough1), ignoreNULL = FALSE)

  output$Plot <- renderPlotly({
    values <- history_data()
    validate(need(nrow(values), "No requests match these filters"))
    plot_ly(values, x = ~date, y = ~value, type = "scatter", mode = "lines", name = input$data2view) %>%
      layout(title = "NYC311 Service Requests(SRs)", xaxis = list(title = "Date", zerolinecolor = "#ffffff", gridcolor = "#ffffff"), yaxis = list(title = "Number of SRs", zerolinecolor = "#ffffff", gridcolor = "#ffffff"), plot_bgcolor = "#e5ecf6")
  })

  forecast_result <- eventReactive(input$view2, {
    values <- forecast_data()
    validate(need(length(values), "No requests match these filters"))
    horizon <- max(1, as.integer(input$h %||% 12))
    forecast_for_apps(as.numeric(values), horizon, input$Model)
  }, ignoreNULL = FALSE)

  output$Plot2 <- renderPlotly({
    result <- forecast_result()
    values <- forecast_data()
    horizon <- max(1, as.integer(input$h %||% 12))
    prediction <- as.numeric(unlist(result$forecast))
    lower <- as.numeric(unlist(result$lower))
    upper <- as.numeric(unlist(result$upper))
    history_dates <- seq(
      as.Date(sprintf("%04d-%02d-01", start(values)[1], start(values)[2])),
      by = "month",
      length.out = length(values)
    )
    future_dates <- seq(tail(history_dates, 1), by = "month", length.out = horizon + 1)[-1]
    history_frame <- data.frame(date = history_dates, value = as.numeric(values))
    forecast_frame <- data.frame(date = future_dates, value = prediction, lower = lower, upper = upper)
    plot_ly() %>%
      add_trace(data = history_frame, x = ~date, y = ~value, name = "Real", type = "scatter", mode = "lines", line = list(color = "blue")) %>%
      add_trace(data = forecast_frame, x = ~date, y = ~value, name = paste(result$model, "forecast"), type = "scatter", mode = "lines", line = list(color = "red")) %>%
      add_ribbons(data = forecast_frame, x = ~date, ymin = ~lower, ymax = ~upper, name = "Approximate range", line = list(color = "transparent"), fillcolor = "rgba(180,180,180,.25)") %>%
      layout(title = paste("Monthly SRs Forecast with", result$model, "Model"), xaxis = list(title = "Date", zerolinecolor = "#000000", gridcolor = "#ffffff"), yaxis = list(title = "Number of SRs", zerolinecolor = "#000000", gridcolor = "#ffffff"), plot_bgcolor = "#e5ecf6")
  })

  output$forecast_status <- renderText({
    result <- forecast_result()
    paste0(
      "Selected ", result$model, "; holdout MAE ",
      format(round(result$validation_mae, 1), big.mark = ","),
      ". MLflow run: ", result$best_run_id, "."
    )
  })

  staffing_result <- eventReactive(input$optimize_staffing, {
    history <- monthly_series("OpenedSR", input$staffing_borough)
    validate(need(length(history) >= 24, "At least 24 monthly observations are required."))
    result <- forecast_for_apps(
      as.numeric(history),
      as.integer(input$staffing_horizon),
      input$staffing_model
    )
    staffing <- optimize_staffing(
      as.numeric(unlist(result$forecast)),
      calls_per_request = input$calls_per_request,
      handle_time_minutes = input$handle_time,
      operating_hours_per_day = input$operating_hours,
      business_days_per_month = as.integer(input$business_days),
      hourly_wage = input$hourly_wage,
      shrinkage = input$shrinkage / 100,
      occupancy_limit = input$occupancy_limit / 100,
      service_level_target = input$service_target / 100,
      answer_seconds = input$answer_seconds
    )
    list(forecast = result, staffing = staffing, history = history)
  })

  output$staffing_plot <- renderPlotly({
    result <- staffing_result()
    staffing <- result$staffing
    last_month <- as.Date(format(time(result$history)[length(result$history)], "%Y-%m-01"))
    months <- seq(last_month, by = "month", length.out = nrow(staffing) + 1)[-1]
    plot_ly() %>%
      add_bars(x = months, y = staffing$fixed_monthly_cost, name = "Fixed peak staffing baseline", marker = list(color = "#9ca3af")) %>%
      add_bars(x = months, y = staffing$monthly_labor_cost, name = "Forecast-optimized labor cost", marker = list(color = "#0c7c86")) %>%
      layout(
        barmode = "group",
        title = "Monthly labor cost at forecast-driven staffing",
        xaxis = list(title = "Month"),
        yaxis = list(title = "Estimated monthly labor cost ($)")
      )
  })

  output$staffing_summary <- renderText({
    result <- staffing_result()
    staffing <- result$staffing
    paste0(
      "Forecast: ", result$forecast$model,
      " (holdout MAE ", format_number(result$forecast$validation_mae, 1),
      "; MLflow run ", result$forecast$best_run_id, "). Recommended call-takers: ",
      min(staffing$call_takers), "–", max(staffing$call_takers),
      ". Modeled service level is at least ",
      format_number(min(staffing$service_level) * 100, 1),
      "% with peak occupancy ",
      format_number(max(staffing$occupancy) * 100, 1), "%",
      ". Estimated savings vs fixed peak staffing: $",
      format_number(sum(staffing$monthly_savings)),
      ". Planning estimate only; schedules must account for intraday peaks, breaks, and labor rules."
    )
  })
}

shinyApp(ui, server)
