"""
AWS S3 Storage Module for AI Media Workflow Dashboard
Handles all file uploads/downloads to/from S3 for cloud deployment
"""

import os
import boto3
from botocore.exceptions import ClientError
from pathlib import Path
import mimetypes

class S3Storage:
    """Handles file storage operations with AWS S3"""
    
    def __init__(self):
        """Initialize S3 client with credentials from environment variables"""
        self.enabled = os.getenv('USE_S3', 'false').lower() == 'true'
        
        if self.enabled:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                region_name=os.getenv('AWS_REGION', 'us-east-1')
            )
            self.bucket_name = os.getenv('S3_BUCKET_NAME')
            self.cloudfront_url = os.getenv('CLOUDFRONT_URL', '')  # Optional CDN
            
            if not self.bucket_name:
                print("⚠️  S3 enabled but S3_BUCKET_NAME not set!")
                self.enabled = False
        else:
            print("📁 Using local file storage (S3 disabled)")
            self.s3_client = None
            self.bucket_name = None
            self.cloudfront_url = None
    
    def upload_file(self, local_file_path, s3_key):
        """
        Upload a file to S3
        
        Args:
            local_file_path: Path to local file
            s3_key: S3 object key (path in bucket, e.g. 'library/image.png')
        
        Returns:
            str: Public URL of uploaded file, or local path if S3 disabled
        """
        if not self.enabled:
            # S3 disabled - return local file path
            return f"/static/{s3_key}"
        
        try:
            # Determine content type
            content_type, _ = mimetypes.guess_type(local_file_path)
            if content_type is None:
                content_type = 'application/octet-stream'
            
            # Upload file
            extra_args = {
                'ContentType': content_type,
                'ACL': 'public-read'  # Make file publicly accessible
            }
            
            self.s3_client.upload_file(
                local_file_path,
                self.bucket_name,
                s3_key,
                ExtraArgs=extra_args
            )
            
            # Return public URL
            if self.cloudfront_url:
                return f"{self.cloudfront_url}/{s3_key}"
            else:
                return f"https://{self.bucket_name}.s3.amazonaws.com/{s3_key}"
                
        except ClientError as e:
            print(f"❌ S3 upload error: {e}")
            # Fallback to local path
            return f"/static/{s3_key}"
    
    def download_file(self, s3_key, local_file_path):
        """
        Download a file from S3
        
        Args:
            s3_key: S3 object key
            local_file_path: Where to save the file locally
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.enabled:
            # S3 disabled - file should already be local
            return os.path.exists(local_file_path)
        
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
            
            # Download file
            self.s3_client.download_file(
                self.bucket_name,
                s3_key,
                local_file_path
            )
            return True
            
        except ClientError as e:
            print(f"❌ S3 download error: {e}")
            return False
    
    def delete_file(self, s3_key):
        """
        Delete a file from S3
        
        Args:
            s3_key: S3 object key
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.enabled:
            # S3 disabled - delete local file
            try:
                local_path = f"static/{s3_key}"
                if os.path.exists(local_path):
                    os.remove(local_path)
                return True
            except Exception as e:
                print(f"❌ Local file delete error: {e}")
                return False
        
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            return True
            
        except ClientError as e:
            print(f"❌ S3 delete error: {e}")
            return False
    
    def file_exists(self, s3_key):
        """
        Check if a file exists in S3
        
        Args:
            s3_key: S3 object key
        
        Returns:
            bool: True if file exists, False otherwise
        """
        if not self.enabled:
            # Check local filesystem
            return os.path.exists(f"static/{s3_key}")
        
        try:
            self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            return True
        except ClientError:
            return False
    
    def get_public_url(self, s3_key):
        """
        Get public URL for a file
        
        Args:
            s3_key: S3 object key
        
        Returns:
            str: Public URL
        """
        if not self.enabled:
            return f"/static/{s3_key}"
        
        if self.cloudfront_url:
            return f"{self.cloudfront_url}/{s3_key}"
        else:
            return f"https://{self.bucket_name}.s3.amazonaws.com/{s3_key}"
    
    def save_uploaded_file(self, file_object, s3_key):
        """
        Save an uploaded Flask file object to S3
        
        Args:
            file_object: Flask request.files object
            s3_key: S3 object key (destination path)
        
        Returns:
            str: Public URL of saved file
        """
        if not self.enabled:
            # Save locally
            local_path = f"static/{s3_key}"
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            file_object.save(local_path)
            return f"/static/{s3_key}"
        
        try:
            # Get content type
            content_type = file_object.content_type or 'application/octet-stream'
            
            # Upload directly from file object
            self.s3_client.upload_fileobj(
                file_object,
                self.bucket_name,
                s3_key,
                ExtraArgs={
                    'ContentType': content_type,
                    'ACL': 'public-read'
                }
            )
            
            return self.get_public_url(s3_key)
            
        except ClientError as e:
            print(f"❌ S3 upload error: {e}")
            # Fallback to local save
            local_path = f"static/{s3_key}"
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            file_object.save(local_path)
            return f"/static/{s3_key}"


# Global instance
storage = S3Storage()


# Convenience functions for easy importing
def upload_file(local_path, s3_key):
    """Upload a local file to S3 or keep local if S3 disabled"""
    return storage.upload_file(local_path, s3_key)

def download_file(s3_key, local_path):
    """Download a file from S3 or use local if S3 disabled"""
    return storage.download_file(s3_key, local_path)

def delete_file(s3_key):
    """Delete a file from S3 or local storage"""
    return storage.delete_file(s3_key)

def get_public_url(s3_key):
    """Get public URL for a file"""
    return storage.get_public_url(s3_key)

def save_uploaded_file(file_object, s3_key):
    """Save uploaded Flask file to S3 or local"""
    return storage.save_uploaded_file(file_object, s3_key)

def is_s3_enabled():
    """Check if S3 storage is enabled"""
    return storage.enabled


