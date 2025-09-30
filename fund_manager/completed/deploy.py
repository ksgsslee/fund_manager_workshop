"""
deploy.py

Fund Manager 배포 스크립트
AgentCore Memory와 Fund Manager Runtime 순차 배포
"""

import sys
import time
import json
from pathlib import Path
from bedrock_agentcore_starter_toolkit import Runtime

# 공통 설정 및 shared 모듈 경로 추가
root_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_path))
sys.path.insert(0, str(root_path / "shared"))

from config import Config as GlobalConfig
from runtime_utils import create_agentcore_runtime_role

class Config:
    """Fund Manager 배포 설정"""
    REGION = GlobalConfig.REGION
    AGENT_NAME = GlobalConfig.FUND_MANAGER_NAME

def load_memory_info():
    """AgentCore Memory 배포 정보 로드"""
    info_file = Path(__file__).parent / "agentcore_memory" / "deployment_info.json"
    if not info_file.exists():
        print("❌ AgentCore Memory 배포 정보가 없습니다.")
        print("💡 먼저 다음 명령을 실행하세요:")
        print("   cd agentcore_memory")
        print("   python deploy_agentcore_memory.py")
        raise FileNotFoundError("AgentCore Memory를 먼저 배포해주세요.")
    
    with open(info_file) as f:
        return json.load(f)

def load_agent_arns():
    """다른 에이전트들의 ARN 정보 로드"""
    base_dir = Path(__file__).parent.parent.parent
    agent_dirs = {
        "FINANCIAL_ANALYST_ARN": "financial_analyst/completed",
        "PORTFOLIO_ARCHITECT_ARN": "portfolio_architect/completed", 
        "RISK_MANAGER_ARN": "risk_manager/completed"
    }
    
    arns = {}
    missing_agents = []
    
    for env_var_name, agent_dir in agent_dirs.items():
        info_file = base_dir / agent_dir / "deployment_info.json"
        if info_file.exists():
            with open(info_file, 'r') as f:
                agent_info = json.load(f)
                arns[env_var_name] = agent_info["agent_arn"]
        else:
            missing_agents.append(agent_dir)
    
    if missing_agents:
        print("❌ 다음 에이전트들이 배포되지 않았습니다:")
        for agent in missing_agents:
            print(f"   - {agent}")
        print("💡 먼저 Lab 1, 2, 3을 완료하여 모든 에이전트를 배포해주세요.")
        raise FileNotFoundError("모든 에이전트를 먼저 배포해주세요.")
    
    return arns

def deploy_fund_manager(memory_info, agent_arns):
    """Fund Manager Runtime 배포"""
    print("🎯 Fund Manager 배포 중...")
    
    # IAM 역할 생성
    iam_role = create_agentcore_runtime_role(Config.AGENT_NAME, Config.REGION)
    iam_role_name = iam_role['Role']['RoleName']
    
    # Runtime 구성
    current_dir = Path(__file__).parent
    runtime = Runtime()
    runtime.configure(
        entrypoint=str(current_dir / "fund_manager.py"),
        execution_role=iam_role['Role']['Arn'],
        auto_create_ecr=True,
        requirements_file=str(current_dir / "requirements.txt"),
        region=Config.REGION,
        agent_name=Config.AGENT_NAME
    )
    
    # 환경변수 설정
    env_vars = {
        "FUND_MEMORY_ID": memory_info['memory_id'],
        "AWS_REGION": Config.REGION
    }
    
    # 다른 에이전트 ARN들 추가
    env_vars.update(agent_arns)
    
    # 배포 실행
    launch_result = runtime.launch(auto_update_on_conflict=True, env_vars=env_vars)
    
    # 배포 완료 대기
    for i in range(30):  # 최대 15분 대기
        try:
            status = runtime.status().endpoint['status']
            print(f"📊 상태: {status} ({i*30}초 경과)")
            if status in ['READY', 'CREATE_FAILED', 'DELETE_FAILED', 'UPDATE_FAILED']:
                break
        except Exception as e:
            print(f"⚠️ 상태 확인 오류: {e}")
        time.sleep(30)
    
    if status != 'READY':
        raise Exception(f"배포 실패: {status}")
    
    # ECR 리포지토리 이름 추출
    ecr_repo_name = None
    if hasattr(launch_result, 'ecr_uri') and launch_result.ecr_uri:
        ecr_repo_name = launch_result.ecr_uri.split('/')[-1].split(':')[0]
    
    return {
        "agent_arn": launch_result.agent_arn,
        "agent_id": launch_result.agent_id,
        "region": Config.REGION,
        "iam_role_name": iam_role_name,
        "ecr_repo_name": ecr_repo_name
    }

def save_deployment_info(memory_info, fund_manager_info):
    """배포 정보 저장"""
    deployment_info = {
        "agent_name": Config.AGENT_NAME,
        "agent_arn": fund_manager_info["agent_arn"],
        "agent_id": fund_manager_info["agent_id"],
        "region": Config.REGION,
        "iam_role_name": fund_manager_info["iam_role_name"],
        "ecr_repo_name": fund_manager_info.get("ecr_repo_name"),
        "memory_id": memory_info["memory_id"],
        "deployed_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    info_file = Path(__file__).parent / "deployment_info.json"
    with open(info_file, 'w') as f:
        json.dump(deployment_info, f, indent=2)
    
    return str(info_file)

def main():
    try:
        print("🎯 Fund Manager 전체 시스템 배포")
        
        # Memory 정보 로드 (필수)
        memory_info = load_memory_info()
        print("✅ AgentCore Memory 정보 로드 완료")
        
        # 다른 에이전트 ARN 정보 로드 (필수)
        agent_arns = load_agent_arns()
        print("✅ 모든 에이전트 ARN 정보 로드 완료")
        
        # Fund Manager 배포
        fund_manager_info = deploy_fund_manager(memory_info, agent_arns)
        
        # 배포 정보 저장
        info_file = save_deployment_info(memory_info, fund_manager_info)
        
        print(f"\n🎉 배포 완료!")
        print(f"📄 배포 정보: {info_file}")
        print(f"🔗 Fund Manager ARN: {fund_manager_info['agent_arn']}")
        print(f"🧠 Memory ID: {memory_info['memory_id']}")
        
        return 0
        
    except Exception as e:
        print(f"❌ 배포 실패: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

