"""
portfolio_architect.py

Portfolio Architect - AI 포트폴리오 설계사
MCP Server 연동으로 실시간 ETF 데이터 기반 포트폴리오 설계
"""

import json
import os
import requests
from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamablehttp_client
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

class Config:
    """Portfolio Architect 설정"""
    MODEL_ID = "global.anthropic.claude-sonnet-4-20250514-v1:0"  # Claude 4.0 Sonnet (global cross region)
    TEMPERATURE = 0.3  # 창의적이면서도 일관된 결과
    MAX_TOKENS = 3000

class PortfolioArchitect:
    def __init__(self, mcp_server_info):
        self.mcp_server_info = mcp_server_info
        self._setup_auth()
        self._init_mcp_client()
        self._create_agent()

    def _setup_auth(self):
        """Cognito OAuth2 토큰 획득"""
        info = self.mcp_server_info
        self.mcp_url = info['mcp_url']
        
        pool_domain = info['user_pool_id'].replace("_", "").lower()
        token_url = f"https://{pool_domain}.auth.{info['region']}.amazoncognito.com/oauth2/token"
        
        response = requests.post(
            token_url,
            data=f"grant_type=client_credentials&client_id={info['client_id']}&client_secret={info['client_secret']}",
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        response.raise_for_status()
        self.access_token = response.json()['access_token']

    def _init_mcp_client(self):
        """MCP 클라이언트 초기화"""
        self.mcp_client = MCPClient(
            lambda: streamablehttp_client(
                self.mcp_url, 
                headers={"Authorization": f"Bearer {self.access_token}"}
            )
        )

    def _create_agent(self):
        """AI 에이전트 생성"""
        with self.mcp_client as client:
            tools = client.list_tools_sync()
            
            self.agent = Agent(
                name="portfolio_architect",
                model=BedrockModel(
                    model_id=Config.MODEL_ID,
                    temperature=Config.TEMPERATURE,
                    max_tokens=Config.MAX_TOKENS
                ),
                system_prompt=self._get_prompt(),
                tools=tools
            )

    def _get_prompt(self):
        return """당신은 전문 투자 설계사입니다. 고객의 재무 분석 결과를 바탕으로 최적의 투자 포트폴리오를 설계해야 합니다.

재무 분석 결과가 다음과 같은 JSON 형식으로 제공됩니다:
{
  "risk_profile": <위험 성향>,
  "risk_profile_reason": <위험 성향 평가 근거>,
  "required_annual_return_rate": <필요 연간 수익률>,
  "key_sectors": <추천 투자 섹터 리스트>,
  "summary": <종합 총평>
}

포트폴리오 설계 프로세스:

1. 후보 ETF 선정: key_sectors와 위험 성향을 고려하여 5개 ETF 후보를 선정하세요.
2. 성과 분석: 선정된 5개 ETF에 대해 "analyze_etf_performance" 도구로 각각의 성과를 분석하세요.
3. 상관관계 분석: "calculate_correlation" 도구로 5개 ETF 간의 상관관계를 분석하세요.
4. 최적 3개 ETF 선정: 성과 분석과 상관관계 결과를 종합하여 최적의 3개 ETF를 선정하세요.
   - 예상 수익률과 분산투자 효과를 균형있게 고려하세요.
   - 목표 수익률 달성 가능성과 리스크 분산을 동시에 만족하는 조합을 선택하세요.
5. 최적 비중 결정: 선정된 3개 ETF의 성과와 상관관계를 바탕으로 최적의 투자 비중을 결정하세요.
6. 포트폴리오 평가: 다음 3가지 지표로 1~10점 평가하세요:
   - 수익성: 목표 수익률 달성 가능성
   - 리스크 관리: 변동성과 손실 확률 수준
   - 분산투자 완성도: 상관관계와 자산군 다양성

최종 결과를 다음 JSON 형식으로 출력하세요:
{
  "portfolio_allocation": {"ticker1": 50, "ticker2": 30, "ticker3": 20},
  "reason": "포트폴리오 구성 근거 및 투자 전략 설명. 각 ETF에 대한 간단한 설명을 반드시 포함하세요.",
  "portfolio_scores": {
    "profitability": {"score": 9, "reason": "구체적 근거"},
    "risk_management": {"score": 7, "reason": "구체적 근거"},
    "diversification": {"score": 8, "reason": "구체적 근거"}
  }
}

주의사항:
- 투자 비중은 정수로 표현하고 총합이 100%가 되어야 합니다."""

    async def design_portfolio_async(self, financial_analysis):
        analysis_str = json.dumps(financial_analysis, ensure_ascii=False)
        
        with self.mcp_client:
            async for event in self.agent.stream_async(analysis_str):
                if "data" in event:
                    yield {"type": "text_chunk", "data": event["data"]}
                
                if "message" in event:
                    message = event["message"]
                    
                    if message.get("role") == "assistant":
                        for content in message.get("content", []):
                            if "toolUse" in content:
                                tool_use = content["toolUse"]
                                yield {
                                    "type": "tool_use",
                                    "tool_name": tool_use.get("name"),
                                    "tool_use_id": tool_use.get("toolUseId"),
                                    "tool_input": tool_use.get("input", {})
                                }
                    
                    if message.get("role") == "user":
                        for content in message.get("content", []):
                            if "toolResult" in content:
                                tool_result = content["toolResult"]
                                yield {
                                    "type": "tool_result",
                                    "tool_use_id": tool_result["toolUseId"],
                                    "status": tool_result["status"],
                                    "content": tool_result["content"]
                                }
                
                if "result" in event:
                    yield {"type": "streaming_complete", "result": str(event["result"])}

# 전역 인스턴스
architect = None

@app.entrypoint
async def portfolio_architect(payload):
    global architect
    
    if architect is None:
        # 환경변수에서 MCP Server 정보 구성
        region = os.getenv("AWS_REGION", "us-west-2")
        mcp_agent_arn = os.getenv("MCP_AGENT_ARN")
        encoded_arn = mcp_agent_arn.replace(':', '%3A').replace('/', '%2F')
        
        mcp_server_info = {
            "mcp_url": f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT",
            "region": region,
            "client_id": os.getenv("MCP_CLIENT_ID"),
            "client_secret": os.getenv("MCP_CLIENT_SECRET"),
            "user_pool_id": os.getenv("MCP_USER_POOL_ID")
        }
        
        architect = PortfolioArchitect(mcp_server_info)

    input_data = payload.get("input_data")
    async for chunk in architect.design_portfolio_async(input_data):
        yield chunk

if __name__ == "__main__":
    app.run()

