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

resource "aws_ecr_repository" "mas_runtime" {
  name                 = var.mas_runtime_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.mas_runtime_image_repository_name
    Purpose   = "mas-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "mas_runtime" {
  repository = aws_ecr_repository.mas_runtime.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 MAS runtime images"
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

resource "aws_ecr_repository" "mas_base" {
  name                 = var.mas_base_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.mas_base_image_repository_name
    Purpose   = "mas-base"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "mas_base" {
  repository = aws_ecr_repository.mas_base.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 MAS base images"
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

resource "aws_ecr_repository" "mas_orchestrator" {
  name                 = var.mas_orchestrator_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.mas_orchestrator_image_repository_name
    Purpose   = "mas-orchestrator"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "mas_orchestrator" {
  repository = aws_ecr_repository.mas_orchestrator.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 MAS orchestrator images"
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

resource "aws_ecr_repository" "mas_observer" {
  name                 = var.mas_observer_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.mas_observer_image_repository_name
    Purpose   = "mas-observer"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "mas_observer" {
  repository = aws_ecr_repository.mas_observer.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 MAS observer images"
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

resource "aws_ecr_repository" "mas_analyzer" {
  name                 = var.mas_analyzer_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.mas_analyzer_image_repository_name
    Purpose   = "mas-analyzer"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "mas_analyzer" {
  repository = aws_ecr_repository.mas_analyzer.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 MAS analyzer images"
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

resource "aws_ecr_repository" "mas_ui" {
  name                 = var.mas_ui_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.mas_ui_image_repository_name
    Purpose   = "mas-ui"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "mas_ui" {
  repository = aws_ecr_repository.mas_ui.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 MAS UI images"
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
