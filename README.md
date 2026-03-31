# vesta

A small Python formatter / previewer / publisher for Vestaboard devices.

The goal is simple:

**semantic input → compact board layout → terminal preview → optional publish**

This repo is intentionally focused on practical personal use, not a big template language or a hosted service.

## What it does

- formats structured data for Vestaboard
- supports multiple device profiles
  - flagship board: **6 x 22**
  - note: **3 x 15**
- previews output in the terminal before sending
- can publish via:
  - Vestaboard Cloud API
  - Vestaboard Local API

## Current templates

- `text` — simple wrapped text
- `kv` — key/value rows
- `table` — compact table rendering
- `metrics` — opinionated compact metrics layout
- `auto` — picks a reasonable renderer based on input shape

## Why this exists

Hitting the Vestaboard API directly is easy.

The harder and more useful part is:
- making structured data fit well
- compacting timestamps and numbers
- previewing output locally
- reusing layouts across scripts and data sources

This project is mainly about that rendering layer.

## Current status

This is still an MVP.

Some areas are intentionally experimental, especially:
- semantic color / tone indicators
- ANSI terminal preview behavior
- how much styling logic belongs in templates vs shared helpers

Comments in the code should call out anything that is still being tried and may change.

## Example usage

Render a metrics payload in the terminal:

```bash
cat metrics.json | python vesta.py render --template metrics
