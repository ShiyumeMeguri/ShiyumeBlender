from PIL import Image

def adjust_image_alpha_abs(image_path):
    # 打开图像
    img = Image.open(image_path)
    img = img.convert('RGBA')  # 确保图像是RGBA模式

    # 获取图像数据
    pixels = img.load()

    # 图像尺寸
    width, height = img.size

    # 遍历每一个像素
    for x in range(width):
        for y in range(height):
            r, g, b, a = pixels[x, y]
            
            # 减去指定的RGB值，如果结果小于0则取绝对值
            r = abs(r - 255) if r - 255 < 0 else r - 255
            g = abs(g - 240) if g - 240 < 0 else g - 240
            b = abs(b - 236) if b - 236 < 0 else b - 236

            # 计算新的alpha值为修改后的RGB值的和
            new_alpha = r + g + b

            # 设置新的像素值
            pixels[x, y] = (r, g, b, new_alpha)

    # 返回修改后的图像
    return img

# 调用函数处理图像
result_image = adjust_image_alpha_abs('path_to_your_image.png')
result_image.save('modified_image_alpha_abs.png')  # 保存图像
