package com.basiclab.iot.sink.domain.model;

import com.fasterxml.jackson.annotation.JsonAlias;
import lombok.Data;

import java.util.List;

/**
 * 人脸匹配 Kafka 消息 DTO
 */
@Data
public class FaceMatchingMessage {

    @JsonAlias("task_id")
    private Integer taskId;

    @JsonAlias("task_name")
    private String taskName;

    @JsonAlias("task_type")
    private String taskType;

    @JsonAlias("device_id")
    private String deviceId;

    @JsonAlias("device_name")
    private String deviceName;

    @JsonAlias("library_id")
    private Integer libraryId;

    @JsonAlias("library_name")
    private String libraryName;

    @JsonAlias("face_image_path")
    private String faceImagePath;

    private Double threshold;

    @JsonAlias("face_matching_threshold")
    private Double faceMatchingThreshold;

    @JsonAlias("alert_id")
    private Integer alertId;

    private List<Integer> bbox;

    private Double confidence;

    private String timestamp;
}
