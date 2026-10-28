# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目

- 名称：Hidden Shelf（中文名：藏片阁）
- 路径：`~/Claude-Code/Hidden-Shelf`
- 状态：v0.0.1 · 筹备中，2026-10-28 建目录。具体需求由用户稍后给出，拿到需求后先用 superpowers:brainstorming 梳理，再更新本文件的「命令」「架构」两节。
- 与用户交流用中文，代码标识符保持原样。

## 命令

待定。确定技术栈后在这里补：安装依赖、启动开发、构建、lint、跑全部测试、跑单个测试。

## 架构

待定。确定方案后在这里写跨文件才能看懂的「大图」（数据流、模块边界、关键约定），不罗列目录。

## 约定

- 每次改代码同步更新版本号（当前 v0.0.1，位置待定：package.json 或等价文件）。
- 版本、技术栈、状态有大变化时同步更新 `~/Claude-Code/PROJECTS.md`。
- 做 Web 界面前按 `~/.claude/rules/frontend-ux.md` 判断加载 `ux-standard` 还是 `frontend-design`。

## 端口约束

- 本项目还没有分配端口。需要端口时先 `cat ~/.claude/ports.md` 读完整表，按表中规则选段，用 `lsof -iTCP -sTCP:LISTEN -nP | grep :<端口>` 确认空闲，分配后写回 ports.md 并在本节登记。
