---
title: Главная
---

<div class="sa-hero" markdown>

# SpeedAssembly {#speedassembly}

Подготовьте растения из SpeedTree к импорту в Unreal Engine. SpeedAssembly читает [Raw XML](wiki/xml-usd-usda-json.md#xml-carries-the-speedtree-source) и экспортирует [USDA](wiki/xml-usd-usda-json.md#usda-is-usd-you-can-read), сохраняя скелет, базовую геометрию, инстансы веток и листвы и материалы.

[Начать основной workflow](workflows/prepare-unreal.md){ .md-button .md-button--primary }

</div>

SpeedAssembly создан специально для работы с растительностью в Unreal Engine 5.7–5.8.

## Выберите workflow {#choose-a-workflow}

<div class="grid cards" markdown>

-   **Основная конвертация в USDA**

    Создайте Skeletal Assembly, Static Assembly или библиотеку веток и листвы из SpeedTree Raw XML.

-   **Dynamic Wind**

    Настройте группы костей и экспортируйте Dynamic Wind [JSON](wiki/xml-usd-usda-json.md#json-carries-the-wind-settings) для анимации ветра в Unreal.

-   **Proxy Mesh**

    Создайте упрощённый Static Mesh для коллизий, distance fields и shadow proxy.

-   **Fracturing**

    Разбейте дерево на отдельные статичные части для разрушения в Unreal. Pivot всех частей остаётся в корне дерева. При необходимости добавьте коллизии.

</div>
