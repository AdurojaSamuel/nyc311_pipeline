#!/usr/bin/env Rscript

#!/usr/bin/env Rscript

library(shiny)
library(plotly)
library(forecast)
library(arrow)

options(shiny.port = as.integer(Sys.getenv("SHINY_PORT", unset = "3838")))
options(shiny.host = Sys.getenv("SHINY_HOST", unset = "0.0.0.0"))

`%||%` <- function(x, y) if (is.null(x) || length(x) == 0) y else x

root <- "/srv/shiny-server"

data_root <- Sys.getenv(
  "NYC311_DATA_ROOT",
  unset = root
)

dashboard_file <- file.path(
  data_root,
  "dashboard_data.parquet"
)

if (!file.exists(dashboard_file)) {
  stop(
    "Dashboard data not found at: ",
    dashboard_file
  )
}

data <- arrow::read_parquet(dashboard_file)

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
  start <- c(as.integer(format(min(monthly$month), "%Y")), as.integer(format(min(monthly$month), "%m")))
  ts(monthly$value, start = start, frequency = 12)
}

ui <- fluidPage(
  title = "Opened and Closed Service Requests",
  tags$head(tags$style(HTML("html, body { height: 100%; } body { overflow: hidden; font-family: Arial, sans-serif; color: #333; } .title-panel { margin: 6px 1.5% 8px; } .control-panel { background: #f5f5f5; border: 1px solid #ddd; border-radius: 4px; padding: 16px; min-height: 214px; } .chart-panel { height: 38vh; } .forecast-panel { height: 48vh; } .orange-rule { border-top: 1px solid orange; margin: 18px 1.5% 14px; } .footnote { height: 5vh; line-height: 5vh; text-align: left; margin: 0; padding: 0 1.5%; position: relative; color: #666; font-size: 12px; } .copyright { position: absolute; left: 50%; transform: translateX(-50%); font-weight: 700; color: #1f3a5f; }"))),
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
      radioButtons("Model", "Model type", c("Holt-Winters", "ARIMA", "LSTM"), inline = TRUE, selected = "Holt-Winters"),
      actionButton("view2", "view", class = "btn-primary")
    )),
    column(8, plotlyOutput("Plot2", height = "48vh"))
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

  output$Plot2 <- renderPlotly({
    values <- forecast_data()
    validate(need(length(values), "No requests match these filters"))
    horizon <- max(1, as.integer(input$h %||% 12))
    model <- input$Model
    if (model == "ARIMA") fit <- auto.arima(values) else if (model == "Holt-Winters") fit <- ets(values) else fit <- NULL
    if (is.null(fit)) {
      seasonal_lag <- min(12, length(values))
      prediction <- rep(tail(values, seasonal_lag), length.out = horizon)
      residuals <- if (length(values) > seasonal_lag) {
        values[(seasonal_lag + 1):length(values)] - values[1:(length(values) - seasonal_lag)]
      } else {
        diff(values)
      }
      residual_sd <- if (length(residuals) > 1) sd(residuals, na.rm = TRUE) else sd(values, na.rm = TRUE)
      residual_sd <- if (is.finite(residual_sd)) residual_sd else 0
      interval <- 1.96 * residual_sd * sqrt(seq_len(horizon))
      lower <- pmax(prediction - interval, 0)
      upper <- prediction + interval
    } else {
      forecasted <- forecast(fit, h = horizon)
      prediction <- as.numeric(forecasted$mean)
      lower <- as.numeric(forecasted$lower[, ncol(forecasted$lower)])
      upper <- as.numeric(forecasted$upper[, ncol(forecasted$upper)])
    }
    history_dates <- as.Date(format(zoo::as.yearmon(time(values)), "%Y-%m-01"))
    future_dates <- seq(max(history_dates) + 32, by = "month", length.out = horizon)
    history_frame <- data.frame(date = history_dates, value = as.numeric(values))
    forecast_frame <- data.frame(date = future_dates, value = prediction, lower = lower, upper = upper)
    plot_ly() %>%
      add_trace(data = history_frame, x = ~date, y = ~value, name = "Real", type = "scatter", mode = "lines", line = list(color = "blue")) %>%
      add_trace(data = forecast_frame, x = ~date, y = ~value, name = "Forecast", type = "scatter", mode = "lines", line = list(color = "red")) %>%
      add_ribbons(data = forecast_frame, x = ~date, ymin = ~lower, ymax = ~upper, name = "95% confidence", line = list(color = "transparent"), fillcolor = "rgba(180,180,180,.25)") %>%
      layout(title = paste("Monthly SRs Forecast with", model, "Model"), xaxis = list(title = "Date", zerolinecolor = "#000000", gridcolor = "#ffffff"), yaxis = list(title = "Number of SRs", zerolinecolor = "#000000", gridcolor = "#ffffff"), plot_bgcolor = "#e5ecf6")
  })
}

shinyApp(ui, server)
