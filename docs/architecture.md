# Architecture

## Overview

Playwright → Parser → Bronze → dbt Silver → dbt Gold → Dashboard

## Extraction

Playwright is responsible for:
- navigating category pages
- selecting the product listing
- extracting raw product attributes

## Parsing

Parser is responsible for:
- validating product type
- extracting power
- creating RawPanel objects

## Bronze

Bronze stores source-level data with minimal transformation.

## Silver

dbt transforms raw textual values into typed analytical columns.

## Gold

dbt creates business-ready analytical models and rankings.

## Orchestration

Airflow will orchestrate:
1. extraction
2. ingestion
3. dbt run
4. dbt test