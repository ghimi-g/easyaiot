package com.basiclab.iot.sink.service.impl;

import com.basiclab.iot.common.utils.json.JsonUtils;
import com.basiclab.iot.sink.domain.model.FaceMatchingMessage;
import com.basiclab.iot.sink.service.FaceMatchingService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.HashMap;
import java.util.Map;

/**
 * 人脸匹配业务实现：调用 VIDEO 模块异步匹配接口
 */
@Slf4j
@Service
public class FaceMatchingServiceImpl implements FaceMatchingService {

    @Autowired(required = false)
    private RestTemplate restTemplate;

    @Autowired(required = false)
    private KafkaTemplate<String, String> iotKafkaTemplate;

    @Value("${basiclab.video.service-url:http://localhost:48080}")
    private String videoServiceUrl;

    @Value("${spring.kafka.face-matching.result-topic:iot-face-matching-result}")
    private String resultTopic;

    @Override
    public void process(FaceMatchingMessage message) {
        if (message == null) {
            throw new IllegalArgumentException("人脸匹配消息为空");
        }
        if (message.getLibraryId() == null) {
            throw new IllegalArgumentException("libraryId 不能为空");
        }
        if (message.getFaceImagePath() == null || message.getFaceImagePath().isEmpty()) {
            throw new IllegalArgumentException("faceImagePath 不能为空");
        }

        if (restTemplate == null) {
            restTemplate = new RestTemplate();
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("taskId", message.getTaskId());
        payload.put("taskName", message.getTaskName());
        payload.put("taskType", message.getTaskType());
        payload.put("deviceId", message.getDeviceId());
        payload.put("deviceName", message.getDeviceName());
        payload.put("libraryId", message.getLibraryId());
        payload.put("libraryName", message.getLibraryName());
        payload.put("faceImagePath", message.getFaceImagePath());
        payload.put("threshold", message.getThreshold() != null ? message.getThreshold() : message.getFaceMatchingThreshold());
        payload.put("alertId", message.getAlertId());
        payload.put("bbox", message.getBbox());
        payload.put("confidence", message.getConfidence());

        String url = normalizeBaseUrl(videoServiceUrl) + "/video/face/matching/process";
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(payload, headers);

        log.info("开始调用人脸匹配: deviceId={}, libraryId={}, path={}",
                message.getDeviceId(), message.getLibraryId(), message.getFaceImagePath());

        ResponseEntity<String> response = restTemplate.postForEntity(url, entity, String.class);
        if (!response.getStatusCode().is2xxSuccessful()) {
            throw new IllegalStateException("VIDEO 人脸匹配接口返回异常: status=" + response.getStatusCodeValue()
                    + ", body=" + response.getBody());
        }

        log.info("人脸匹配处理完成: deviceId={}, libraryId={}, response={}",
                message.getDeviceId(), message.getLibraryId(), response.getBody());

        publishResult(message, response.getBody());
    }

    private void publishResult(FaceMatchingMessage message, String processResponseBody) {
        if (iotKafkaTemplate == null) {
            return;
        }
        try {
            Map<String, Object> result = new HashMap<>();
            result.put("deviceId", message.getDeviceId());
            result.put("libraryId", message.getLibraryId());
            result.put("faceImagePath", message.getFaceImagePath());
            result.put("taskId", message.getTaskId());
            result.put("processResponse", processResponseBody);
            result.put("timestamp", message.getTimestamp());
            iotKafkaTemplate.send(resultTopic, message.getDeviceId(), JsonUtils.toJsonString(result));
        } catch (Exception e) {
            log.warn("发送人脸匹配结果到 Kafka 失败: deviceId={}, error={}",
                    message.getDeviceId(), e.getMessage(), e);
        }
    }

    private static String normalizeBaseUrl(String baseUrl) {
        if (baseUrl == null || baseUrl.isEmpty()) {
            return "http://localhost:48080";
        }
        return baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
    }
}
