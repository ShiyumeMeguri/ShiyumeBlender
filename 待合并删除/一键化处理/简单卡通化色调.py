import bpy

def process_materials():
    for material in bpy.data.materials:
        if material.use_nodes:
            nodes = material.node_tree.nodes
            links = material.node_tree.links

            # 查找材质输出节点
            material_output_node = None
            for node in nodes:
                if node.type == 'OUTPUT_MATERIAL':
                    material_output_node = node
                    break

            if not material_output_node:
                continue  # 如果没有找到材质输出节点，跳过这个材质

            # 查找材质中的第一个图像纹理节点
            image_texture_node = None
            for node in nodes:
                if node.type == 'TEX_IMAGE':
                    image_texture_node = node
                    break

            # 如果找到图像纹理节点，则进行处理
            if image_texture_node:
                # 创建或查找乘法的 Mix RGB 节点
                multiply_node = nodes.get("Multiply Mix")
                if not multiply_node:
                    multiply_node = nodes.new(type='ShaderNodeMixRGB')
                    multiply_node.name = "Multiply Mix"
                    multiply_node.blend_type = 'MULTIPLY'
                    multiply_node.inputs['Fac'].default_value = 1.0
                    multiply_node.inputs['Color2'].default_value = (2, 2, 2, 1.0)
                
                # 连接图像纹理节点到乘法节点
                links.new(image_texture_node.outputs['Color'], multiply_node.inputs['Color1'])

                # 创建叠加和数值调整的 Mix RGB 节点
                overlay_node = nodes.get("Overlay Mix")
                if not overlay_node:
                    overlay_node = nodes.new(type='ShaderNodeMixRGB')
                    overlay_node.name = "Overlay Mix"
                    overlay_node.blend_type = 'OVERLAY'
                    overlay_node.inputs['Fac'].default_value = 0.5

                value_node = nodes.get("Value Mix")
                if not value_node:
                    value_node = nodes.new(type='ShaderNodeMixRGB')
                    value_node.name = "Value Mix"
                    value_node.blend_type = 'VALUE'
                    value_node.inputs['Fac'].default_value = 1.0
                    value_node.inputs['Color2'].default_value = (0.439, 0.757, 0.961, 1.0)  # 设置颜色

                # 连接乘法节点到值调整节点和叠加节点
                links.new(multiply_node.outputs['Color'], value_node.inputs['Color1'])
                links.new(value_node.outputs['Color'], overlay_node.inputs['Color2'])
                links.new(multiply_node.outputs['Color'], overlay_node.inputs['Color1'])

                # 断开材质输出节点的所有连接
                for input in material_output_node.inputs:
                    for link in input.links:
                        links.remove(link)

                # 将叠加节点的输出连接到材质输出节点的 Surface
                links.new(overlay_node.outputs['Color'], material_output_node.inputs['Surface'])

# 运行处理函数
process_materials()