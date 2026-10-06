# Частые вопросы {#frequently-asked-questions}

## Может ли Proxy Mesh заменить дерево со скелетом? {#can-proxy-mesh-replace-the-skeletal-tree}

Нет. Proxy Mesh дополняет дерево отдельным Static Mesh. Skeletal Assembly остаётся основным ассетом дерева и основным форматом для импорта.

## Почему Final Polycount не даёт точно указанное количество? {#why-did-final-polycount-not-produce-the-exact-requested-number}

Final Polycount задаёт цель упрощения. Построенная поверхность может содержать меньше треугольников, чем запрошено, или её топология может не позволить безопасно достичь нужного значения. См. [Final Polycount](../workflows/proxy-mesh.md#final-polycount).

## Почему в экспорте Proxy нет коллизий? {#why-is-collision-missing-from-the-proxy-output}

Проверьте следующее:

- **Generate Collision** включён;
- **Height** больше нуля;
- **Width** больше нуля;
- в исходнике достаточно корректной геометрии ствола с привязкой к скелету, чтобы подогнать выбранный примитив.

## Почему увеличение Final Polycount не возвращает мелкие детали листвы? {#why-does-increasing-final-polycount-not-restore-small-foliage-detail}

Детали могли потеряться при построении поверхности по объёму листвы. Увеличьте [Density Resolution](../workflows/proxy-mesh.md#density-resolution) перед увеличением итогового бюджета треугольников.

## Подтверждает ли успешный импорт Proxy хорошее качество distance fields и теней? {#does-successful-proxy-import-prove-good-distance-fields-or-shadows}

Нет. Импорт подтверждён, но результат для distance fields и теней нужно проверять на каждом ассете в целевой сцене Unreal.

## Почему основная конвертация не запускается? {#why-will-the-main-conversion-not-start}

Заполните все обязательные поля найденных материалов Unreal для текущего режима материалов. Элементы со ссылками на существующие ассеты Unreal не требуют этих назначений, потому что сохраняют собственные материалы.

## SpeedAssembly конвертирует любой XML? {#is-speedassembly-a-generic-xml-converter}

Нет. Он создан для наблюдаемой структуры SpeedTree Raw XML и workflow импорта растительности в Unreal Engine 5.7–5.8.
