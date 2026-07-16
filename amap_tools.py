"""
高德地图 API 工具 —— 直接调用高德地图 Web 服务 API。
"""
import httpx
from typing import Optional, Annotated
from langchain_core.tools import tool, StructuredTool
from pydantic import BaseModel, Field
from config import CONFIG


def _geocode_sync(address: str, city: str = "") -> Optional[str]:
    """地理编码：地址转坐标（同步版本）"""
    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {
        "key": CONFIG.amap_key,
        "address": address,
        "city": city
    }
    
    try:
        response = httpx.get(url, params=params, timeout=10)
        data = response.json()
        if data.get("status") == "1":
            geocodes = data.get("geocodes", [])
            if geocodes:
                return geocodes[0].get("location", "")
    except Exception as e:
        print(f"地理编码错误: {e}")
    return None


class WeatherSchema(BaseModel):
    """天气查询参数"""
    city: str = Field(description="城市名称，如'北京'、'上海'、'长沙'")


class POISearchSchema(BaseModel):
    """POI搜索参数"""
    keywords: str = Field(description="搜索关键词，如'酒店'、'景点'、'湘菜'")
    city: str = Field(description="城市名称，如'北京'、'上海'、'长沙'")


class RouteSchema(BaseModel):
    """路线规划参数"""
    origin: str = Field(description="起点地址，如'岳麓山'、'五一广场'")
    destination: str = Field(description="终点地址，如'橘子洲'、'火车站'")


class TransitRouteSchema(BaseModel):
    """公交路线规划参数"""
    origin: str = Field(description="起点地址")
    destination: str = Field(description="终点地址")
    city: str = Field(description="城市名称，用于公交路线规划")


def _maps_weather(city: str) -> str:
    """天气查询函数"""
    url = "https://restapi.amap.com/v3/weather/weatherInfo"
    params = {
        "key": CONFIG.amap_key,
        "city": city,
        "extensions": "all"
    }
    
    try:
        response = httpx.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("status") != "1":
            return f"天气查询失败: {data.get('info', '未知错误')}"
        
        forecasts = data.get("forecasts", [])
        if not forecasts:
            return f"未找到{city}的天气信息"
        
        result_parts = []
        for forecast in forecasts:
            city_name = forecast.get("city", city)
            casts = forecast.get("casts", [])
            for cast in casts[:3]:
                date = cast.get("date", "")
                day_weather = cast.get("dayweather", "")
                night_weather = cast.get("nightweather", "")
                day_temp = cast.get("daytemp", "")
                night_temp = cast.get("nighttemp", "")
                wind_dir = cast.get("daywind", "")
                wind_power = cast.get("daypower", "")
                
                result_parts.append(
                    f"{date}: 白天{day_weather} {day_temp}°C, 夜间{night_weather} {night_temp}°C, "
                    f"风向{wind_dir} 风力{wind_power}级"
                )
        
        return f"{city_name}天气预报:\n" + "\n".join(result_parts)
    
    except Exception as e:
        return f"天气查询异常: {str(e)}"


def _maps_text_search(keywords: str, city: str) -> str:
    """POI搜索函数"""
    url = "https://restapi.amap.com/v3/place/text"
    params = {
        "key": CONFIG.amap_key,
        "keywords": keywords,
        "city": city,
        "citylimit": "true",
        "offset": 10,
        "page": 1,
        "extensions": "all"
    }
    
    try:
        response = httpx.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("status") != "1":
            return f"搜索失败: {data.get('info', '未知错误')}"
        
        pois = data.get("pois", [])
        if not pois:
            return f"未找到与'{keywords}'相关的地点"
        
        result_parts = []
        for i, poi in enumerate(pois[:5], 1):
            name = poi.get("name", "")
            address = poi.get("address", "")
            type_name = poi.get("type", "")
            tel = poi.get("tel", "")
            
            biz_ext = poi.get("biz_ext", {}) or {}
            rating = biz_ext.get("rating", "")
            cost = biz_ext.get("cost", "")
            
            info = f"{i}. {name}"
            if type_name:
                info += f" ({type_name})"
            if address and address != "NULL":
                info += f"\n   地址: {address}"
            if tel:
                info += f"\n   电话: {tel}"
            if rating:
                info += f"\n   评分: {rating}分"
            if cost:
                info += f"\n   人均: {cost}元"
            result_parts.append(info)
        
        return f"搜索'{keywords}'结果:\n" + "\n".join(result_parts)
    
    except Exception as e:
        return f"搜索异常: {str(e)}"


def _maps_direction_walking_by_address(origin: str, destination: str) -> str:
    """步行路线规划函数"""
    origin_location = _geocode_sync(origin)
    dest_location = _geocode_sync(destination)
    
    if not origin_location:
        return f"无法获取起点'{origin}'的坐标，请确认地址是否正确"
    if not dest_location:
        return f"无法获取终点'{destination}'的坐标，请确认地址是否正确"
    
    url = "https://restapi.amap.com/v3/direction/walking"
    params = {
        "key": CONFIG.amap_key,
        "origin": origin_location,
        "destination": dest_location
    }
    
    try:
        response = httpx.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("status") != "1":
            return f"路线规划失败: {data.get('info', '未知错误')}"
        
        route = data.get("route", {})
        paths = route.get("paths", [])
        if not paths:
            return "未找到可行路线"
        
        path = paths[0]
        distance = int(path.get("distance", 0))
        duration = int(path.get("duration", 0))
        
        distance_km = distance / 1000
        duration_min = duration // 60
        
        return f"步行路线: {origin} → {destination}\n距离: {distance_km:.1f}公里\n预计时间: {duration_min}分钟"
    
    except Exception as e:
        return f"路线规划异常: {str(e)}"


def _maps_direction_driving_by_address(origin: str, destination: str) -> str:
    """驾车路线规划函数"""
    origin_location = _geocode_sync(origin)
    dest_location = _geocode_sync(destination)
    
    if not origin_location:
        return f"无法获取起点'{origin}'的坐标，请确认地址是否正确"
    if not dest_location:
        return f"无法获取终点'{destination}'的坐标，请确认地址是否正确"
    
    url = "https://restapi.amap.com/v3/direction/driving"
    params = {
        "key": CONFIG.amap_key,
        "origin": origin_location,
        "destination": dest_location,
        "extensions": "base"
    }
    
    try:
        response = httpx.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("status") != "1":
            return f"路线规划失败: {data.get('info', '未知错误')}"
        
        route = data.get("route", {})
        paths = route.get("paths", [])
        if not paths:
            return "未找到可行路线"
        
        path = paths[0]
        distance = int(path.get("distance", 0))
        duration = int(path.get("duration", 0))
        
        distance_km = distance / 1000
        duration_min = duration // 60
        fuel_cost = distance_km * 0.6
        
        return (f"驾车路线: {origin} → {destination}\n"
                f"距离: {distance_km:.1f}公里\n"
                f"预计时间: {duration_min}分钟\n"
                f"预估油费: {fuel_cost:.0f}元")
    
    except Exception as e:
        return f"路线规划异常: {str(e)}"


def _maps_direction_transit_integrated_by_address(origin: str, destination: str, city: str) -> str:
    """公交路线规划函数"""
    if not city:
        return "公交路线规划需要提供城市名称"
    
    origin_location = _geocode_sync(origin, city)
    dest_location = _geocode_sync(destination, city)
    
    if not origin_location:
        return f"无法获取起点'{origin}'的坐标，请确认地址是否正确"
    if not dest_location:
        return f"无法获取终点'{destination}'的坐标，请确认地址是否正确"
    
    url = "https://restapi.amap.com/v3/direction/transit/integrated"
    params = {
        "key": CONFIG.amap_key,
        "origin": origin_location,
        "destination": dest_location,
        "city": city,
        "cityd": city
    }
    
    try:
        response = httpx.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("status") != "1":
            return f"路线规划失败: {data.get('info', '未知错误')}"
        
        route = data.get("route", {})
        transits = route.get("transits", [])
        if not transits:
            return "未找到可行公交路线"
        
        result_parts = []
        for i, transit in enumerate(transits[:2], 1):
            cost = transit.get("cost", {})
            duration = int(cost.get("duration", 0))
            distance = int(cost.get("distance", 0))
            walking_distance = int(cost.get("walking_distance", 0))
            transit_fee = cost.get("transit_fee", "0")
            
            duration_min = duration // 60
            distance_km = distance / 1000
            walk_km = walking_distance / 1000
            
            segments = transit.get("segments", [])
            steps = []
            for seg in segments:
                bus = seg.get("bus", {})
                if bus:
                    buslines = bus.get("buslines", [])
                    if buslines:
                        line_name = buslines[0].get("name", "")
                        via_stops = buslines[0].get("via_num", 0)
                        steps.append(f"乘{line_name}({via_stops}站)")
                walking = seg.get("walking", {})
                if walking:
                    walk_dist = int(walking.get("distance", 0))
                    if walk_dist > 100:
                        steps.append(f"步行{walk_dist}米")
            
            result_parts.append(
                f"方案{i}: {duration_min}分钟, {distance_km:.1f}公里, "
                f"步行{walk_km:.1f}公里, 票价{transit_fee}元\n"
                f"  路线: {' → '.join(steps)}"
            )
        
        return f"公交路线: {origin} → {destination}\n" + "\n".join(result_parts)
    
    except Exception as e:
        return f"路线规划异常: {str(e)}"


# 使用 StructuredTool 创建工具，提供明确的 schema
maps_weather = StructuredTool.from_function(
    name="maps_weather",
    description="查询城市天气信息。输入城市名称，返回天气概况。",
    func=_maps_weather,
    args_schema=WeatherSchema,
)

maps_text_search = StructuredTool.from_function(
    name="maps_text_search",
    description="搜索地点信息（酒店、景点、餐厅等）。输入关键词和城市，返回地点列表。",
    func=_maps_text_search,
    args_schema=POISearchSchema,
)

maps_direction_walking_by_address = StructuredTool.from_function(
    name="maps_direction_walking_by_address",
    description="规划步行路线。输入起点和终点地址，返回步行路线信息。",
    func=_maps_direction_walking_by_address,
    args_schema=RouteSchema,
)

maps_direction_driving_by_address = StructuredTool.from_function(
    name="maps_direction_driving_by_address",
    description="规划驾车路线。输入起点和终点地址，返回驾车路线信息。",
    func=_maps_direction_driving_by_address,
    args_schema=RouteSchema,
)

maps_direction_transit_integrated_by_address = StructuredTool.from_function(
    name="maps_direction_transit_integrated_by_address",
    description="规划公交/地铁路线。输入起点、终点地址及城市，返回公交路线信息。",
    func=_maps_direction_transit_integrated_by_address,
    args_schema=TransitRouteSchema,
)


def get_amap_tools():
    """获取所有高德地图工具"""
    return [
        maps_weather,
        maps_text_search,
        maps_direction_walking_by_address,
        maps_direction_driving_by_address,
        maps_direction_transit_integrated_by_address,
    ]
