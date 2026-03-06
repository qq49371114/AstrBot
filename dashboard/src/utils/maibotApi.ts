/**
 * MaiBot API 工具函数
 * 处理与后端 MaiBot 管理接口的通信
 */

import axios from "axios";

// API 基础 URL
const API_BASE_URL = "/api/maibot";

// 创建 axios 实例
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  headers: {
    "Content-Type": "application/json",
  },
});

// 请求拦截器：添加认证 token
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers["Authorization"] = `Bearer ${token}`;
  }
  return config;
});

// 响应数据接口
export interface ApiResponse<T = any> {
  success?: string;
  status?: string;
  message?: string;
  data?: T;
  error?: string;
  [key: string]: any; // 允许访问 any 属性
}

// 实例信息接口
export interface InstanceInfo {
  id: string;
  name: string;
  description: string;
  status:
    | "stopped"
    | "starting"
    | "running"
    | "stopping"
    | "error"
    | "restarting";
  is_default: boolean;
  host: string;
  port: number;
  web_host: string;
  web_port: number;
  enable_webui: boolean;
  enable_socket: boolean;
  lifecycle?: {
    start_order?: number;
    restart_on_crash?: boolean;
    max_restarts?: number;
    restart_delay?: number;
    auto_start?: boolean;
  };
  logging?: {
    enable_console?: boolean;
    log_level?: string;
  };
  knowledge_base?: {
    enabled?: boolean;
    path?: string;
    kb_names?: string[];
    fusion_top_k?: number;
    return_top_k?: number;
    long_thinking_enabled?: boolean;
  };
  created_at: string;
  updated_at: string;
  started_at?: string;
  uptime?: number;
  message_count?: number;
  error_message?: string;
  last_message_time?: string;
}

// 路由规则接口
export interface RoutingRule {
  chat_id: string;
  instance_id: string;
}

/**
 * 获取所有实例
 */
export async function getInstances(): Promise<InstanceInfo[]> {
  try {
    const response =
      await apiClient.get<ApiResponse<{ instances: InstanceInfo[] }>>(
        "/instances",
      );
    if (response.data.data?.instances) {
      // 映射后端字段到前端期望的字段
      return response.data.data.instances.map((inst) => ({
        id: inst.id || (inst as any).instance_id,
        name: inst.name,
        description: inst.description,
        status: inst.status,
        is_default: inst.is_default,
        host: inst.host,
        port: inst.port,
        web_host: inst.web_host,
        web_port: inst.web_port,
        enable_webui: inst.enable_webui,
        enable_socket: inst.enable_socket,
        lifecycle: inst.lifecycle,
        logging: inst.logging,
        knowledge_base: inst.knowledge_base,
        created_at: inst.created_at,
        updated_at: inst.updated_at,
        started_at: inst.started_at,
        uptime: inst.uptime,
        message_count: inst.message_count,
        error_message: inst.error_message,
        last_message_time: inst.last_message_time,
      }));
    }
    return [];
  } catch (error) {
    console.error("获取实例列表失败:", error);
    throw error;
  }
}

/**
 * 获取运行中的实例列表
 */
export async function getRunningInstances(): Promise<InstanceInfo[]> {
  try {
    const response =
      await apiClient.get<ApiResponse<{ instances: InstanceInfo[] }>>(
        "/running",
      );
    if (response.data.data?.instances) {
      return response.data.data.instances.map((inst) => ({
        id: inst.id || (inst as any).instance_id,
        name: inst.name,
        description: inst.description,
        status: inst.status,
        is_default: inst.is_default,
        host: inst.host,
        port: inst.port,
        web_host: inst.web_host,
        web_port: inst.web_port,
        enable_webui: inst.enable_webui,
        enable_socket: inst.enable_socket,
        lifecycle: inst.lifecycle,
        logging: inst.logging,
        knowledge_base: inst.knowledge_base,
        created_at: inst.created_at,
        updated_at: inst.updated_at,
        started_at: inst.started_at,
        uptime: inst.uptime,
        message_count: inst.message_count,
        error_message: inst.error_message,
        last_message_time: inst.last_message_time,
      }));
    }
    return [];
  } catch (error) {
    console.error("获取运行中实例列表失败:", error);
    throw error;
  }
}

/**
 * 获取单个实例详情
 */
export async function getInstance(instanceId: string): Promise<InstanceInfo> {
  try {
    const response = await apiClient.get<ApiResponse<InstanceInfo>>(
      `/instances/${instanceId}`,
    );
    if (response.data.status === "ok" && response.data.data) {
      return response.data.data;
    }
    throw new Error(response.data.message || "实例不存在");
  } catch (error) {
    console.error(`获取实例 ${instanceId} 详情失败:`, error);
    throw error;
  }
}

/**
 * 创建新实例
 */
export async function createInstance(data: {
  instance_id: string;
  name: string;
  description?: string;
  port?: number;
  copy_from?: string;
  enable_webui?: boolean;
  enable_socket?: boolean;
  config_updates?: Record<string, any>; // 配置修改项（会与模板合并）
}): Promise<InstanceInfo> {
  try {
    const response = await apiClient.post<ApiResponse<InstanceInfo>>(
      "/instances",
      data,
    );
    if (response.data.status === "ok" && response.data.data) {
      return response.data.data;
    }
    throw new Error(response.data.message || "创建实例失败");
  } catch (error) {
    console.error("创建实例失败:", error);
    throw error;
  }
}

/**
 * 更新实例元数据配置（instances_meta.json 中的字段）
 * 会同步更新 TOML 文件中的相关配置
 */
export async function updateInstance(
  instanceId: string,
  data: {
    name?: string;
    description?: string;
    lifecycle?: {
      restart_on_crash?: boolean;
      max_restarts?: number;
      restart_delay?: number;
      auto_start?: boolean;
    };
    host?: string;
    port?: number;
    web_host?: string;
    web_port?: number;
    enable_webui?: boolean;
    enable_socket?: boolean;
    logging?: {
      enable_console?: boolean;
      log_level?: string;
    };
    knowledge_base?: {
      enabled?: boolean;
      path?: string;
      kb_names?: string[];
      fusion_top_k?: number;
      return_top_k?: number;
      long_thinking_enabled?: boolean;
    };
  },
): Promise<InstanceInfo> {
  try {
    const response = await apiClient.put<ApiResponse<InstanceInfo>>(
      `/instances/${instanceId}`,
      data,
    );
    // 支持 success 和 status 两种响应格式
    if ((response.data.success || response.data.status === "ok") && response.data.data) {
      return response.data.data;
    }
    throw new Error(response.data.error || response.data.message || "更新实例失败");
  } catch (error) {
    console.error(`更新实例 ${instanceId} 失败:`, error);
    throw error;
  }
}

/**
 * 删除实例
 */
export async function deleteInstance(
  instanceId: string,
  deleteData: boolean = false,
): Promise<void> {
  try {
    const response = await apiClient.delete<ApiResponse>(
      `/instances/${instanceId}`,
      {
        params: { delete_data: deleteData },
      },
    );
    if (response.data.status !== "ok") {
      throw new Error(response.data.error || "删除实例失败");
    }
  } catch (error) {
    console.error(`删除实例 ${instanceId} 失败:`, error);
    throw error;
  }
}

/**
 * 启动实例
 */
export async function startInstance(instanceId: string): Promise<void> {
  try {
    const response = await apiClient.post<ApiResponse>(
      `/instances/${instanceId}/start`,
    );
    if (response.data.status !== "ok") {
      throw new Error(response.data.error || "启动实例失败");
    }
  } catch (error) {
    console.error(`启动实例 ${instanceId} 失败:`, error);
    throw error;
  }
}

/**
 * 停止实例
 */
export async function stopInstance(instanceId: string): Promise<void> {
  try {
    const response = await apiClient.post<ApiResponse>(
      `/instances/${instanceId}/stop`,
    );
    if (response.data.status !== "ok") {
      throw new Error(response.data.error || "停止实例失败");
    }
  } catch (error) {
    console.error(`停止实例 ${instanceId} 失败:`, error);
    throw error;
  }
}

/**
 * 重启实例
 */
export async function restartInstance(instanceId: string): Promise<void> {
  try {
    const response = await apiClient.post<ApiResponse>(
      `/instances/${instanceId}/restart`,
    );
    if (response.data.status !== "ok") {
      throw new Error(response.data.error || "重启实例失败");
    }
  } catch (error) {
    console.error(`重启实例 ${instanceId} 失败:`, error);
    throw error;
  }
}

/**
 * 获取实例配置
 */
export async function getInstanceConfig(instanceId: string): Promise<any> {
  try {
    const response = await apiClient.get<ApiResponse>(
      `/instances/${instanceId}/config`,
    );
    if (response.data.status === "ok" && response.data.data) {
      return response.data.data.config;
    }
    throw new Error(response.data.message || "获取配置失败");
  } catch (error) {
    console.error(`获取实例 ${instanceId} 配置失败:`, error);
    throw error;
  }
}

/**
 * 保存实例配置
 * @param instanceId 实例ID
 * @param config 配置数据对象（可选）
 * @param rawContent 原始 TOML 内容（可选，与 config 二选一）
 */
export async function saveInstanceConfig(
  instanceId: string,
  config?: any,
  rawContent?: string,
): Promise<void> {
  try {
    const payload: any = {};
    if (config !== undefined) {
      payload.config = config;
    }
    if (rawContent !== undefined) {
      payload.raw_content = rawContent;
    }

    const response = await apiClient.put<ApiResponse>(
      `/instances/${instanceId}/config`,
      payload,
    );
    if (response.data.status !== "ok") {
      throw new Error(response.data.message || "保存配置失败");
    }
  } catch (error) {
    console.error(`保存实例 ${instanceId} 配置失败:`, error);
    throw error;
  }
}

/**
 * 获取路由规则
 */
export async function getRoutingRules(): Promise<{
  default_instance: string;
  rules: RoutingRule[];
}> {
  try {
    const response = await apiClient.get<ApiResponse>("/routing/rules");
    if (response.data.success && response.data.data) {
      return response.data.data;
    }
    throw new Error("获取路由规则失败");
  } catch (error) {
    console.error("获取路由规则失败:", error);
    throw error;
  }
}

/**
 * 保存路由规则
 */
export async function saveRoutingRules(data: {
  default_instance: string;
  rules: RoutingRule[];
}): Promise<void> {
  try {
    const response = await apiClient.put<ApiResponse>("/routing/rules", data);
    if (response.data.status !== "ok") {
      throw new Error(response.data.error || "保存路由规则失败");
    }
  } catch (error) {
    console.error("保存路由规则失败:", error);
    throw error;
  }
}

/**
 * 获取实例日志
 */
export async function getInstanceLogs(
  instanceId: string,
  limit: number = 100,
  offset: number = 0,
): Promise<{
  logs: string[];
  total: number;
}> {
  try {
    const response = await apiClient.get<ApiResponse>(
      `/instances/${instanceId}/logs`,
      {
        params: { limit, offset },
      },
    );
    // 后端使用 Response().ok().__dict__ 格式，返回 { status: "ok", data: {...} }
    if (response.data.status === "ok" && response.data.data) {
      return response.data.data;
    }
    throw new Error(response.data.message || "获取日志失败");
  } catch (error) {
    console.error(`获取实例 ${instanceId} 日志失败:`, error);
    throw error;
  }
}

/**
 * 清空实例日志
 */
export async function clearInstanceLogs(instanceId: string): Promise<void> {
  try {
    const response = await apiClient.post<ApiResponse>(
      `/instances/${instanceId}/logs/clear`,
    );
    if (response.data.status !== "ok") {
      throw new Error(response.data.message || "清空日志失败");
    }
  } catch (error) {
    console.error(`清空实例 ${instanceId} 日志失败:`, error);
    throw error;
  }
}

/**
 * 下载实例日志
 */
export async function downloadInstanceLogs(instanceId: string): Promise<void> {
  try {
    const response = await apiClient.get(
      `/instances/${instanceId}/logs/download`,
      { responseType: "blob" },
    );

    if (response.data) {
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", `${instanceId}_logs.txt`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    }
  } catch (error) {
    console.error(`下载实例 ${instanceId} 日志失败:`, error);
    throw error;
  }
}



/**
 * 获取共用的 data.txt 内容
 */
export async function getDataTxt(): Promise<{
  content: string;
  exists: boolean;
}> {
  try {
    const response = await apiClient.get<ApiResponse>("/data");
    if (response.data.status === "ok" && response.data.data) {
      return {
        content: response.data.data.content || "",
        exists: response.data.data.exists || false,
      };
    }
    throw new Error(response.data.message || "获取文本库失败");
  } catch (error) {
    console.error("获取文本库失败:", error);
    throw error;
  }
}

/**
 * 保存共用的 data.txt 内容
 */
export async function saveDataTxt(content: string): Promise<void> {
  try {
    const response = await apiClient.put<ApiResponse>("/data", {
      content,
    });
    if (response.data.status !== "ok") {
      throw new Error(response.data.message || "保存文本库失败");
    }
  } catch (error) {
    console.error("保存文本库失败:", error);
    throw error;
  }
}

/**
 * 获取默认模板配置
 */
export async function getDefaultTemplateConfig(): Promise<any> {
  try {
    const response = await apiClient.get<ApiResponse>(
      "/instances/default_config",
    );
    if (response.data.status === "ok" && response.data.data) {
      return response.data.data;
    }
    throw new Error(response.data.message || "获取默认配置失败");
  } catch (error) {
    console.error("获取默认模板配置失败:", error);
    throw error;
  }
}

export default {
  getInstances,
  getRunningInstances,
  getInstance,
  createInstance,
  updateInstance,
  deleteInstance,
  startInstance,
  stopInstance,
  restartInstance,
  getInstanceConfig,
  getDefaultTemplateConfig,
  saveInstanceConfig,
  getRoutingRules,
  saveRoutingRules,
  getInstanceLogs,
  clearInstanceLogs,
  downloadInstanceLogs,
  getDataTxt,
  saveDataTxt,
};
