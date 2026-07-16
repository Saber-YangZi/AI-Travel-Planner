"""
MCP 客户端管理器 —— 临时替换为假数据，不调用高德API
"""
from langchain_core.tools import Tool
from config import CONFIG

class McpClientManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._tools_cache = {}
        self._initialized = True

    async def get_all_tools(self) -> list[Tool]:
        if "all" not in self._tools_cache:
            def weather_func(city):
                return '{"status":"1","count":"3","info":"OK","infocode":"10000","forecasts":{"city":"%s","adcode":"430100","province":"湖南","reporttime":"2026-05-20 18:00:00","casts":[{"date":"2026-05-21","week":"3","dayweather":"晴","nightweather":"多云","daytemp":"28","nighttemp":"20","daywind":"南","nightwind":"南","daypower":"2-3级","nightpower":"2-3级"},{"date":"2026-05-22","week":"4","dayweather":"多云","nightweather":"晴","daytemp":"30","nighttemp":"22","daywind":"东南","nightwind":"东南","daypower":"1-2级","nightpower":"1-2级"},{"date":"2026-05-23","week":"5","dayweather":"晴","nightweather":"小雨","daytemp":"29","nighttemp":"21","daywind":"南","nightwind":"南","daypower":"2-3级","nightpower":"2-3级"}]}}' % city

            def poi_func(keywords=None, city="长沙"):
                return '{"status":"1","count":"10","info":"OK","infocode":"10000","pois":[{"id":"B0FFFAB1GH5","name":"橘子洲","type":"旅游景点;公园","typecode":"110201","address":"湖南省长沙市岳麓区橘洲路","location":"112.938888,28.228312","tel":"0731-88886666","distance":"","biz_type":"","shopinfo":"0","poiweight":"100","gridcode":"","cityname":"长沙","adname":"岳麓区","importance":"","timestamp":"","tag":"","level":"","match":"","recommend":"","alias":"","business_area":"","parking_type":"","exit_location":"","service_type":"","rating":"4.7","cost":"免费","open_time":"08:00-22:00"},{"id":"B0FFFAB1GH6","name":"岳麓山国家重点风景名胜区","type":"旅游景点;公园","typecode":"110201","address":"湖南省长沙市岳麓区登高路58号","location":"112.926488,28.189882","tel":"0731-88825011","distance":"","biz_type":"","shopinfo":"0","poiweight":"95","gridcode":"","cityname":"长沙","adname":"岳麓区","importance":"","timestamp":"","tag":"","level":"","match":"","recommend":"","alias":"","business_area":"","parking_type":"","exit_location":"","service_type":"","rating":"4.6","cost":"免费","open_time":"06:00-22:00"},{"id":"B0FFFAB1GH7","name":"湖南省博物馆","type":"旅游景点;博物馆","typecode":"110301","address":"湖南省长沙市开福区东风路50号","location":"112.986788,28.209882","tel":"0731-84415300","distance":"","biz_type":"","shopinfo":"0","poiweight":"90","gridcode":"","cityname":"长沙","adname":"开福区","importance":"","timestamp":"","tag":"","level":"","match":"","recommend":"","alias":"","business_area":"","parking_type":"","exit_location":"","service_type":"","rating":"4.8","cost":"免费","open_time":"09:00-17:00"},{"id":"B0FFFAB1GH8","name":"太平街","type":"旅游景点;步行街","typecode":"110203","address":"湖南省长沙市天心区五一大道","location":"112.981288,28.192382","tel":"","distance":"","biz_type":"","shopinfo":"0","poiweight":"85","gridcode":"","cityname":"长沙","adname":"天心区","importance":"","timestamp":"","tag":"","level":"","match":"","recommend":"","alias":"","business_area":"","parking_type":"","exit_location":"","service_type":"","rating":"4.5","cost":"免费","open_time":"全天"},{"id":"B0FFFAB1GH9","name":"IFS国金中心","type":"购物服务;商场","typecode":"060101","address":"湖南省长沙市芙蓉区解放西路188号","location":"112.983488,28.196882","tel":"0731-88888888","distance":"","biz_type":"","shopinfo":"0","poiweight":"80","gridcode":"","cityname":"长沙","adname":"芙蓉区","importance":"","timestamp":"","tag":"","level":"","match":"","recommend":"","alias":"","business_area":"","parking_type":"","exit_location":"","service_type":"","rating":"4.5","cost":"","open_time":"10:00-22:00"}]}'

            def walking_func(origin=None, destination=None):
                return '{"status":"1","info":"OK","infocode":"10000","route":{"origin":"112.983488,28.196882","destination":"112.986788,28.209882","paths":[{"distance":1200,"duration":18,"steps":[{"distance":100,"duration":2,"instruction":"从起点出发，向北行走100米","road":"解放西路","orientation":"北"},{"distance":200,"duration":3,"instruction":"右转进入黄兴路步行街","road":"黄兴路","orientation":"东"},{"distance":900,"duration":13,"instruction":"继续向东行走900米到达终点","road":"五一大道","orientation":"东"}]}}}'

            def driving_func(origin=None, destination=None):
                return '{"status":"1","info":"OK","infocode":"10000","route":{"origin":"112.983488,28.196882","destination":"112.926488,28.189882","paths":[{"distance":5300,"duration":25,"steps":[{"distance":500,"duration":2,"instruction":"从起点出发，沿解放西路向西行驶500米","road":"解放西路","orientation":"西"},{"distance":3000,"duration":12,"instruction":"左转进入湘江中路，向南行驶3公里","road":"湘江中路","orientation":"南"},{"distance":1800,"duration":11,"instruction":"右转进入登高路，向东行驶1.8公里到达终点","road":"登高路","orientation":"东"}]}}}'

            def transit_func(origin=None, destination=None):
                return '{"status":"1","info":"OK","infocode":"10000","route":{"origin":"112.983488,28.196882","destination":"112.926488,28.189882","transits":[{"cost":2,"duration":35,"walking_distance":500,"lines":[{"name":"地铁2号线","type":"地铁","stops":["五一广场站","溁湾镇站"],"count":3},{"name":"步行","type":"步行","stops":[],"count":0}]}]}}'

            fake_tools = [
                Tool(name="maps_weather", description="查询天气", func=weather_func),
                Tool(name="maps_text_search", description="搜索POI", func=poi_func),
                Tool(name="maps_direction_walking_by_address", description="步行路线", func=walking_func),
                Tool(name="maps_direction_driving_by_address", description="驾车路线", func=driving_func),
                Tool(name="maps_direction_transit_integrated_by_address", description="公交路线", func=transit_func),
            ]
            self._tools_cache["all"] = fake_tools
        return self._tools_cache["all"]

    async def get_tools_for(self, domain: str) -> list[Tool]:
        all_tools = await self.get_all_tools()
        target_names = set(CONFIG.tool_domains.get(domain, []))
        return [t for t in all_tools if t.name in target_names]

    async def close(self):
        pass

    @classmethod
    def reset(cls):
        cls._instance = None
