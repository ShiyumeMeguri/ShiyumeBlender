import cv2
import numpy as np

# 加载两张图像
image1 = cv2.imread('1.png')
image2 = cv2.imread('2.png')

# 确保两张图像大小相同
if image1.shape == image2.shape:
    # 计算两张图像的差异
    diff = cv2.subtract(image2, image1)
    
    # 计算差异的平均值
    avg_diff = np.mean(diff, axis=(0, 1))

    # 初始化LUT
    lut = np.zeros((256, 1, 3), dtype=np.uint8)

    # 计算LUT
    for i in range(256):
        lut[i, 0, 0] = np.clip(i + avg_diff[0], 0, 255)
        lut[i, 0, 1] = np.clip(i + avg_diff[1], 0, 255)
        lut[i, 0, 2] = np.clip(i + avg_diff[2], 0, 255)

    # 应用LUT到原始图像 (示例用image1)
    result_image = cv2.LUT(image1, lut)

    # 显示结果
    cv2.imshow('Result Image', result_image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
else:
    print("Images are not the same size")