---
title: Назначение материалов
description: Назначьте материалы Unreal базовому mesh и repeated parts через Single Material, FBX slots или чёрно-белое разделение по vertex colors.
---

# Назначение материалов {#assigning-materials}

Вкладка **Materials** назначает существующие материалы Unreal базовому mesh растения и [инстансам веток или листьев](../wiki/choosing-assembly-parts.md). Ветке часто нужны разные материалы коры и листвы, даже если в SpeedTree она импортирована как один Leaf mesh.

## Назначьте материалы базовому mesh {#assign-the-base-mesh-materials}

1. В **Content Browser** Unreal нажмите правой кнопкой по материалу или material instance и выберите **Copy Object Path**.
2. В SpeedAssembly откройте **Materials** и вставьте путь в нужную строку **Base Mesh Materials**.
3. Повторите для каждой найденной строки материала.

![Copy Object Path в контекстном меню материала Unreal](../assets/images/conversion-copy-object-path.png){ style="max-height: 550px; width: auto;" }

Используйте полный Object Path, например `/Game/MI_Bark.MI_Bark`. SpeedAssembly блокирует конвертацию, пока обязательные назначения материалов не заполнены.

## Выберите режим материалов для repeated parts {#choose-a-material-mode-for-repeated-parts}

В **Instanced Part Materials** выберите **Part Material Mode** для каждого mesh.

| Режим | Источник | Назначение |
| --- | --- | --- |
| **Single Material** | [XML](../wiki/xml-usd-usda-json.md#xml-carries-the-speedtree-source) или FBX mesh | Один материал Unreal для всего повторяемого mesh. |
| **Material Slots** | FBX replacement | Отдельный материал Unreal для каждого используемого FBX material slot. |
| **Vertex Color Split** | XML или FBX mesh | Два материала Unreal, выбранных по vertex colors mesh. |

Части с **Use Unreal Reference** сохраняют материалы существующего mesh-ассета Unreal вместо назначения здесь.

### Single Material {#single-material}

Выберите **Single Material** и заполните путь к материалу. Используйте этот режим, если mesh нужен один материал или общий материал атласа покрывает и ветку, и листья.

### Material Slots из FBX {#material-slots-from-fbx}

При экспорте Leaf-меша в Raw XML SpeedTree сохраняет одно назначение материала. Чтобы использовать отдельные слоты исходного FBX ветки:

1. В **Geometry** выберите **Use FBX File** для repeated part и укажите файл замены.
2. В **Materials** выберите **Material Slots**.
3. Назначьте материал Unreal каждому показанному FBX slot.

Назначения полигонов слотам в FBX определяют, какие поверхности получат каждый материал. Используемых слотов может быть один, два или больше; для неиспользуемых слотов строки не нужны. Vertex colors для этого режима не требуются.

Pivot, ориентация и реальный размер замены должны совпадать с mesh, использованным в SpeedTree. См. [Подготовку веток и листьев для инстансинга](prepare-speedtree.md#prepare-repeated-branches-and-leaves).

## Vertex Color Split {#vertex-color-split}

Vertex colors хранят RGB-значения на вершинах mesh. Здесь они служат маской для назначения материалов целым полигонам, а не цветами, которые обязан показывать материал Unreal.

Подготовьте одну область в чистом чёрном, другую в чистом белом. Например, листья могут быть чёрными, а кора веточек белой. Обратный вариант тоже работает: назначьте материал листвы тому цвету, которым отмечены листья.

Выберите **Vertex Color Split** и заполните **Black Material** и **White Material** в соответствии с раскраской.

![Назначения Black Material и White Material во вкладке Materials](../assets/images/conversion-materials.png)

### Подготовьте и экспортируйте цвета в SpeedTree {#prepare-and-export-colors-in-speedtree}

Подготовьте mesh ветки с нужными чёрно-белыми областями до использования в Leaf. Разделение должно идти по границам полигонов, а не градиентом между корой и листьями.

1. В графе генераторов SpeedTree выберите корень **Tree**.
2. В его свойствах найдите **Vertex Color** и включите **Compute**, чтобы vertex colors рассчитывались для экспорта.

![Корень Tree выбран, Compute включён в Vertex Color в SpeedTree](../assets/images/materials-speedtree-compute-colors.png){ style="max-height: 750px; width: auto;" }

3. В меню **View** viewport выберите **Vertex Colors > Color**.
4. Проверьте чёрно-белое разделение нужных областей, затем экспортируйте с [настройками XML для SpeedAssembly](prepare-speedtree.md#export-for-speedassembly).

![Меню SpeedTree Vertex Colors > Color с чёрной листвой и белыми ветками](../assets/images/materials-speedtree-view-colors.png)

**Compute** включает расчёт цветов, но не решает, какие поверхности должны получить материал коры или листвы. Ещё раз проверьте экспортированные цвета в SpeedAssembly, особенно после изменения исходного mesh или настроек цвета в SpeedTree.

### Проверьте разделение в Preview/Edit {#check-the-split-in-previewedit}

1. В **Geometry** найдите repeated part и нажмите **Preview/Edit**.

![Вкладка Geometry и кнопка Preview/Edit для отдельного repeated part](../assets/images/materials-open-part-preview.png)

2. В **Material Mode** выберите **Vertex Color** и назначьте **Black Material** и **White Material**.
3. В **Display** выберите **Vertex Colors**, чтобы проверить исходные цвета.

![Preview отдельной части в Vertex Colors с белыми листьями и тёмным стеблем](../assets/images/materials-part-vertex-colors.png)

4. В **Display** выберите **Material Colors**, чтобы проверить полученные области материалов.
5. Нажмите **Apply**, чтобы перенести назначения в главное окно.

В preview доступны те же настройки материалов и UDIM, что и в основных вкладках. Названия **Vertex Color** и **FBX Materials** соответствуют **Vertex Color Split** и **Material Slots** во вкладке Materials. Режимы Display меняют только раскраску preview; они не меняют разделение при экспорте и не отображают назначенные шейдеры Unreal.

### Точные правила для полигонов {#exact-polygon-rules}

Используйте чёрный RGB `(0, 0, 0)` и белый RGB `(1, 1, 1)` для предсказуемого результата с обоими типами источника. Alpha не участвует в выборе материала.

- **XML mesh:** все вершины полигона должны быть чисто чёрными или все чисто белыми. Серый, другие цвета и смешение чёрных и белых вершин внутри полигона не принимаются при явном разделении. Обе группы должны присутствовать.
- **FBX replacement:** полигон получает **Black Material**, только если все его вершины чисто чёрные. Любой другой полигон получает **White Material**. Обе группы должны присутствовать.

Это назначение материалов полигонам, а не плавно смешиваемая маска. Если для mesh нужна только одна область, используйте **Single Material**. Если нужно больше двух независимо назначаемых областей, используйте FBX replacement с **Material Slots**.

## UDIM {#udims}

У каждого подходящего назначения материала есть свой режим UDIM и tile ID, в том числе у двух цветовых областей и отдельных FBX slots.

**Shift UV**, **Write UV1 Offset** и граф материала Unreal для тайловой коры описаны в [UDIM workflow](udim.md). Настройки работают одинаково в Materials и Preview/Edit.
