package com.basiclab.iot.sink.service;

import com.basiclab.iot.sink.domain.model.FaceMatchingMessage;

/**
 * 人脸匹配业务服务
 */
public interface FaceMatchingService {

    /**
     * 处理 Kafka 人脸匹配消息：调用 VIDEO 服务完成 1:N 匹配并落库
     */
    void process(FaceMatchingMessage message);
}
