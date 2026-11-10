---
title: Экспорт PVE Growth Data
description: Экспортируйте скелет дерева и радиусы ветвей из SpeedTree в Growth Data JSON для Unreal Engine 5.8.
---

# Экспорт PVE Growth Data {#export-pve-growth-data}

Этот режим создаёт JSON-файл, с которым можно продолжить работу над деревом в **Procedural Vegetation Editor** в Unreal Engine 5.8. Файл сохраняет форму дерева, длину ветвей и толщину ствола и веток.

## Экспорт из SpeedAssembly {#export-from-speedassembly}

1. Выберите SpeedTree Raw XML в поле **Input XML**.
2. Откройте шестерёнку рядом с **Convert to USDA** и выберите **PVE Growth Data (UE 5.8)**.
3. Нажмите **Export Growth Data**. По умолчанию **Output JSON** использует папку и имя исходного XML.

Настраивать материалы, геометрию и ветер для этого экспорта не нужно. SpeedAssembly использует кривые Spine, если они есть и проходят проверку. Если экспорт выполнен из Bones, причину покажет жёлтое предупреждение.

## Загрузка JSON в Unreal {#load-the-json-in-unreal}

Включите **Procedural Vegetation Editor**. В Content Browser выберите **Add → Data → Data Asset** и создайте **Procedural Vegetation Growth Data Asset**. Откройте ассет, укажите папку с JSON в **Internal → Json Directory Path**, нажмите **UpdateDataAsset** и сохраните ассет. Кнопка загрузит все JSON из папки как вариации.

В графе PVE назначьте ассет в **Growth Data Loader**. Подключите выход нужной вариации к **Mesh Builder** и назначьте материал в **Generation Materials**, чтобы увидеть дерево.
