package com.basiclab.iot.dataset.service.annotation;

import com.basiclab.iot.dataset.dal.dataobject.DatasetTagDO;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;

/**
 * 将标注工具 JSON 转为 YOLO 标签 txt 内容。
 * 兼容 label 存 shortcut（数字/字符串）或类别名。
 */
public final class YoloLabelContentBuilder {

    private static final Logger LOGGER = LoggerFactory.getLogger(YoloLabelContentBuilder.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private YoloLabelContentBuilder() {
    }

    public static Map<String, String> buildShortcutToName(List<DatasetTagDO> tags) {
        Map<String, String> shortcutToName = new HashMap<>();
        Map<String, String> nameToShortcut = DatasetAnnotationParseUtil.nameToShortcutFromTags(tags);
        for (Map.Entry<String, String> entry : nameToShortcut.entrySet()) {
            shortcutToName.put(entry.getValue(), entry.getKey());
        }
        return shortcutToName;
    }

    public static Map<String, String> buildNameToShortcut(List<DatasetTagDO> tags) {
        return DatasetAnnotationParseUtil.nameToShortcutFromTags(tags);
    }

    /**
     * @param classNameToId 类别名 -> YOLO class id；为 null 时不过滤类别
     * @param imageWidth    图片宽，像素坐标归一化用；可为 null
     * @param imageHeight   图片高，像素坐标归一化用；可为 null
     */
    public static String build(String annotationsJson,
                               Map<String, Integer> classNameToId,
                               Map<String, String> shortcutToName,
                               Map<String, String> nameToShortcut,
                               Integer imageWidth,
                               Integer imageHeight) {
        if (annotationsJson == null || annotationsJson.isBlank()) {
            return "";
        }
        try {
            List<Map<String, Object>> anns = MAPPER.readValue(
                    annotationsJson, new TypeReference<List<Map<String, Object>>>() {});
            if (anns == null || anns.isEmpty()) {
                return "";
            }

            int w = imageWidth != null && imageWidth > 0 ? imageWidth : 1;
            int h = imageHeight != null && imageHeight > 0 ? imageHeight : 1;
            StringBuilder sb = new StringBuilder();

            for (Map<String, Object> ann : anns) {
                String rawLabel = extractRawLabel(ann);
                if (rawLabel.isEmpty()) {
                    continue;
                }
                String labelName = resolveLabelName(rawLabel, shortcutToName, nameToShortcut);
                if (labelName == null || labelName.isEmpty()) {
                    continue;
                }
                if (classNameToId != null && !classNameToId.containsKey(labelName)) {
                    continue;
                }

                List<double[]> points = extractPoints(ann.get("points"));
                if (points.size() < 4) {
                    LOGGER.debug("跳过点数不足的标注: label={}, points={}", labelName, points.size());
                    continue;
                }

                double minX = 1, minY = 1, maxX = 0, maxY = 0;
                for (double[] pt : points) {
                    double x = pt[0];
                    double y = pt[1];
                    if (x > 1.01 || y > 1.01) {
                        x /= w;
                        y /= h;
                    }
                    minX = Math.min(minX, x);
                    minY = Math.min(minY, y);
                    maxX = Math.max(maxX, x);
                    maxY = Math.max(maxY, y);
                }

                double cx = (minX + maxX) / 2;
                double cy = (minY + maxY) / 2;
                double bw = maxX - minX;
                double bh = maxY - minY;
                if (bw <= 0 || bh <= 0) {
                    continue;
                }

                int classId = classNameToId != null ? classNameToId.get(labelName) : 0;
                sb.append(String.format(Locale.US, "%d %.6f %.6f %.6f %.6f%n",
                        classId, cx, cy, bw, bh));
            }
            return sb.toString();
        } catch (Exception e) {
            LOGGER.warn("解析标注 JSON 失败: {}", e.getMessage());
            return "";
        }
    }

    private static String extractRawLabel(Map<String, Object> ann) {
        Object labelObj = ann.get("label");
        if (labelObj == null) {
            labelObj = ann.get("class");
        }
        if (labelObj == null) {
            return "";
        }
        return String.valueOf(labelObj).trim();
    }

    /**
     * 将 shortcut / 类别名 / 类别序号解析为标签名称。
     */
    public static String resolveLabelName(String rawLabel,
                                          Map<String, String> shortcutToName,
                                          Map<String, String> nameToShortcut) {
        if (rawLabel == null || rawLabel.isEmpty()) {
            return null;
        }
        Map<String, String> s2n = shortcutToName != null ? shortcutToName : Map.of();
        Map<String, String> n2s = nameToShortcut != null ? nameToShortcut : Map.of();

        if (s2n.containsKey(rawLabel)) {
            return s2n.get(rawLabel);
        }
        if (n2s.containsKey(rawLabel)) {
            return rawLabel;
        }
        if (rawLabel.matches("\\d+")) {
            int num = Integer.parseInt(rawLabel);
            String byShortcut = s2n.get(String.valueOf(num));
            if (byShortcut != null) {
                return byShortcut;
            }
            List<String> names = new ArrayList<>(n2s.keySet());
            if (num >= 0 && num < names.size()) {
                return names.get(num);
            }
            if (num >= 1 && num <= names.size()) {
                return names.get(num - 1);
            }
        }
        return rawLabel;
    }

    @SuppressWarnings("unchecked")
    private static List<double[]> extractPoints(Object pointsObj) {
        List<double[]> result = new ArrayList<>();
        if (!(pointsObj instanceof List<?> points)) {
            return result;
        }
        for (Object item : points) {
            double[] xy = parsePoint(item);
            if (xy != null) {
                result.add(xy);
            }
        }
        return result;
    }

    private static double[] parsePoint(Object item) {
        if (item instanceof Map<?, ?> map) {
            Object xObj = map.get("x");
            Object yObj = map.get("y");
            if (xObj != null && yObj != null) {
                return new double[]{toDouble(xObj), toDouble(yObj)};
            }
        }
        if (item instanceof List<?> arr && arr.size() >= 2) {
            return new double[]{toDouble(arr.get(0)), toDouble(arr.get(1))};
        }
        return null;
    }

    private static double toDouble(Object o) {
        if (o instanceof Number) {
            return ((Number) o).doubleValue();
        }
        return Double.parseDouble(String.valueOf(o));
    }
}
