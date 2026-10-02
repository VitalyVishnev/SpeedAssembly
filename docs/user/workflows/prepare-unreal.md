---
title: Prepare Unreal Engine
description: Enable Nanite Foliage and the Unreal Engine plugins used by the SpeedAssembly workflow.
---

# Prepare Unreal Engine

SpeedAssembly supports Unreal Engine 5.7 and 5.8. The project setup described here is the same in both versions.

Complete these steps once for each Unreal project, before importing plants from SpeedAssembly.

## Enable Nanite Foliage

1. In Unreal Editor, open **Edit > Project Settings**.
2. In the search field, enter `nanite`.
3. Under **Engine > Rendering > Nanite**, make sure **Nanite** is enabled.
4. Enable **Nanite Foliage (Experimental)**.

![Project Settings with Nanite and Nanite Foliage enabled](../assets/images/unreal-nanite-foliage.png)

## Enable plugins

1. In Unreal Editor, open **Edit > Plugins**.
2. Search for `wind` and enable **Dynamic Wind**. This plugin provides wind animation for skeletal Nanite plants.

    ![Dynamic Wind enabled in the Plugins window](../assets/images/unreal-dynamic-wind-plugin.png)

3. Search for `vegetation` and enable **Procedural Vegetation Editor**.

    ![Procedural Vegetation Editor enabled in the Plugins window](../assets/images/unreal-procedural-vegetation-editor-plugin.png)

4. Search for `usd` and enable **Interchange OpenUSD**. This is the plugin used to import SpeedAssembly exports.

    ![Interchange OpenUSD enabled in the Plugins window](../assets/images/unreal-interchange-openusd-plugin.png)

If Unreal asks to enable plugin dependencies, accept. These plugins are marked Experimental in Unreal.

## Restart and check

1. Save your work and restart Unreal Editor to apply the project setting and plugin changes.
2. Reopen **Project Settings** and check that **Nanite Foliage (Experimental)** remains enabled.
3. Reopen **Plugins** and check that **Dynamic Wind**, **Procedural Vegetation Editor**, and **Interchange OpenUSD** are enabled.

Your project is ready for the SpeedAssembly workflow. Import settings and connecting wind data are covered in the separate Unreal import guide.

Next, [prepare your plant in SpeedTree](prepare-speedtree.md).

<!-- Add the Import into Unreal Engine link when that article exists. -->
