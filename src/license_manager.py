import os
import json

class LicenseManager:
    PRICE_MONTHLY = 5
    PRICE_YEARLY = 36
    
    FEATURE_4K = "4k_recording"
    FEATURE_GPU = "gpu_acceleration"
    FEATURE_SYSTEM_AUDIO = "system_audio"
    
    def __init__(self):
        self.vip_status = False # Default to Free user
        # In the future, load this from a secure local file or server
        
    def is_vip(self):
        """Check if the user has a valid VIP license."""
        return self.vip_status
        
    def check_feature_access(self, feature_name):
        """
        Check if the current user can access a specific feature.
        Returns True if allowed, False otherwise.
        """
        if self.is_vip():
            return True
            
        # Free tier limitations
        if feature_name == self.FEATURE_4K:
            return False
        if feature_name == self.FEATURE_GPU:
            return False
        # System audio is currently considered a VIP feature in this model
        if feature_name == self.FEATURE_SYSTEM_AUDIO:
             # Based on user request "4k... VIP", "GPU... VIP". 
             # User didn't explicitly say system audio is VIP in the last prompt, 
             # but the product manager persona suggested it.
             # However, the prompt specific: "1080p/2k 30fps FREE", "4k VIP", "GPU VIP".
             # It didn't explicitly mention system audio in the PRICING prompt.
             # I will follow the specific pricing prompt for now: 4K and GPU are VIP.
             pass
             
        return True

    def get_upgrade_message(self):
        return (
            f"此功能为 VIP 专属。\n"
            f"升级 VIP 仅需 ¥{self.PRICE_MONTHLY}/月 或 ¥{self.PRICE_YEARLY}/年。\n"
            f"支持 4K 60FPS 录制、GPU 硬件加速等高级功能。"
        )