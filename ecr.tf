resource "aws_ecr_repository" "ansible_codebuild" {
  name                 = var.ansible_codebuild_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.ansible_codebuild_image_repository_name
    Purpose   = "ansible-codebuild-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "ansible_codebuild" {
  repository = aws_ecr_repository.ansible_codebuild.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Ansible CodeBuild images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "internal_git" {
  name                 = var.internal_git_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.internal_git_image_repository_name
    Purpose   = "internal-git-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "internal_git" {
  repository = aws_ecr_repository.internal_git.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 internal Git images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "argocd" {
  name                 = var.argocd_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.argocd_image_repository_name
    Purpose   = "argocd-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "argocd" {
  repository = aws_ecr_repository.argocd.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Argo CD images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "argocd_redis" {
  name                 = var.argocd_redis_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.argocd_redis_image_repository_name
    Purpose   = "argocd-redis-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "argocd_redis" {
  repository = aws_ecr_repository.argocd_redis.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Argo CD Redis images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "prometheus" {
  name                 = var.prometheus_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.prometheus_image_repository_name
    Purpose   = "prometheus-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "prometheus" {
  repository = aws_ecr_repository.prometheus.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Prometheus images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "temporal_server" {
  name                 = var.temporal_server_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.temporal_server_image_repository_name
    Purpose   = "temporal-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "temporal_server" {
  repository = aws_ecr_repository.temporal_server.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Temporal server images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "temporal_admin_tools" {
  name                 = var.temporal_admin_tools_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.temporal_admin_tools_image_repository_name
    Purpose   = "temporal-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "temporal_admin_tools" {
  repository = aws_ecr_repository.temporal_admin_tools.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Temporal admin tools images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "temporal_ui" {
  name                 = var.temporal_ui_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.temporal_ui_image_repository_name
    Purpose   = "temporal-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "temporal_ui" {
  repository = aws_ecr_repository.temporal_ui.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Temporal UI images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "istio_pilot" {
  name                 = "${var.istio_image_repository_prefix}/pilot"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "${var.istio_image_repository_prefix}/pilot"
    Purpose   = "istio-ambient-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_repository" "istio_proxyv2" {
  name                 = "${var.istio_image_repository_prefix}/proxyv2"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "${var.istio_image_repository_prefix}/proxyv2"
    Purpose   = "istio-ambient-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_repository" "istio_install_cni" {
  name                 = "${var.istio_image_repository_prefix}/install-cni"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "${var.istio_image_repository_prefix}/install-cni"
    Purpose   = "istio-ambient-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_repository" "istio_ztunnel" {
  name                 = "${var.istio_image_repository_prefix}/ztunnel"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "${var.istio_image_repository_prefix}/ztunnel"
    Purpose   = "istio-ambient-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "istio_pilot" {
  repository = aws_ecr_repository.istio_pilot.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Istio pilot images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "istio_proxyv2" {
  repository = aws_ecr_repository.istio_proxyv2.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Istio proxyv2 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "istio_install_cni" {
  repository = aws_ecr_repository.istio_install_cni.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Istio install-cni images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "istio_ztunnel" {
  repository = aws_ecr_repository.istio_ztunnel.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Istio ztunnel images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "teleport" {
  name                 = var.teleport_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.teleport_image_repository_name
    Purpose   = "teleport-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "teleport" {
  repository = aws_ecr_repository.teleport.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Teleport images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}
