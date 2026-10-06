---
title: Что такое SpeedAssembly?
description: Подготовьте растения из SpeedTree для Nanite Assembly в Unreal Engine с инстансами веток и скелетом для анимации ветра.
---

# Что такое SpeedAssembly? {#what-is-speedassembly}

SpeedAssembly связывает SpeedTree с новым Nanite Assembly workflow в Unreal Engine. Создайте растение в SpeedTree, затем подготовьте его в SpeedAssembly к импорту в Unreal с инстансами веток и листьев и скелетом для анимации ветра.

Инстансинг позволяет много раз использовать один mesh ветки или листа в дереве. SpeedAssembly сохраняет эти инстансы, поэтому одни и те же ассеты веток и листвы можно использовать в разных растениях. Перед импортом в Unreal также можно заменить лёгкие ветки из SpeedTree более детальными моделями.

Кроме основного экспорта дерева, SpeedAssembly позволяет настроить группы симуляции ветра, создать упрощённые mesh для distance fields, shadow proxy и коллизий, а также разбить дерево на части для разрушения.

## Доступные workflows {#supported-workflows}

| Workflow | Что можно создать или настроить |
| --- | --- |
| **Skeletal Assembly** | Целое дерево с инстансами веток и листьев и скелетом для анимации ветра. |
| **Skeletal Assembly Parts** | Отдельные Skeletal Mesh ассеты веток и листвы для использования в других деревьях. |
| **Static Assembly** | Целое дерево с инстансами веток и листьев, без скелета. |
| **Static Assembly Parts** | Отдельные Static Mesh ассеты веток и листвы для использования в других деревьях. |
| **Dynamic Wind JSON** | Настройки ветра для импорта в Unreal и работы с Dynamic Wind. |
| **Wind Preview** | Автоматические или ручные группы костей и их настройки ветра. Можно также создать данные ветра для внешнего FBX- или USD-скелета. |
| **Proxy Mesh** | Low-poly mesh на основе дерева для distance fields и shadow proxy, с необязательными коллизиями ствола. |
| **Fracturing · Experimental** | Разбиение дерева на отдельные статичные части для разрушения в Unreal, с необязательной автоматической генерацией коллизий. |

## С чего начать {#where-to-start}

Прочитайте [обзор pipeline](../concepts/pipeline-overview.md), чтобы увидеть весь путь от SpeedTree до Unreal. Чтобы начать основной workflow, [подготовьте проект Unreal](../workflows/prepare-unreal.md).

Для создания упрощённого mesh дерева см. [Proxy Mesh workflow](../workflows/proxy-mesh.md).

<!-- Add links to the dedicated guides when they exist:
     ../wind/preview-workflow.md
     ../wind/unreal-setup.md
     ../fracturing/overview.md
-->
